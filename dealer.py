"""Core logic for the simple, sequential phone dialer.

The UI can run in demo mode without a telephony provider. Real calls are
isolated behind TwilioProvider and are only enabled when the expected
environment variables are present.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

import phonenumbers


TERMINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}
RETRYABLE_STATUSES = {"busy", "failed", "no-answer", "canceled"}


@dataclass(frozen=True)
class PhoneRecord:
    original: str
    normalized: str | None
    valid: bool
    error: str | None = None


@dataclass
class CallLogEntry:
    timestamp: str
    number: str
    attempt: int
    status: str
    detail: str = ""


def parse_phone_list(content: str, default_region: str = "BR") -> list[PhoneRecord]:
    """Parse one phone number per line, ignoring blanks and # comments."""
    records: list[PhoneRecord] = []
    seen: set[str] = set()

    for raw_line in content.splitlines():
        original = raw_line.strip()
        if not original or original.startswith("#"):
            continue

        try:
            parsed = phonenumbers.parse(
                original,
                None if original.startswith("+") else default_region,
            )
            if not phonenumbers.is_possible_number(parsed):
                raise ValueError("quantidade de dígitos impossível")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError("número não reconhecido como válido")

            normalized = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            if normalized in seen:
                continue
            seen.add(normalized)
            records.append(PhoneRecord(original, normalized, True))
        except (phonenumbers.NumberParseException, ValueError) as error:
            records.append(PhoneRecord(original, None, False, str(error)))

    return records


class CallProvider:
    """Interface used by the worker so demo and real providers behave alike."""

    name = "Provedor"
    is_real = False

    def place_call(self, number: str) -> str:
        raise NotImplementedError

    def wait_for_completion(
        self, call_id: str, stop_event: threading.Event, update: Callable[[str], None]
    ) -> str:
        raise NotImplementedError

    def cancel_call(self, call_id: str) -> None:
        del call_id


class DemoProvider(CallProvider):
    """Safe local provider: never contacts a telephone network."""

    name = "Demonstração"
    is_real = False

    def place_call(self, number: str) -> str:
        del number
        return f"demo-{uuid4().hex[:10]}"

    def wait_for_completion(
        self, call_id: str, stop_event: threading.Event, update: Callable[[str], None]
    ) -> str:
        del call_id
        for remaining in range(3, 0, -1):
            if stop_event.wait(1):
                return "canceled"
            update(f"simulação: aguardando {remaining}s")
        return "completed"


class TwilioProvider(CallProvider):
    """Twilio adapter. Credentials are read from environment variables only."""

    name = "Twilio"
    is_real = True

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        from twilio.rest import Client

        self._client = Client(account_sid, auth_token)
        self._from_number = from_number

    @classmethod
    def from_environment(cls) -> "TwilioProvider | None":
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_FROM_NUMBER")
        if not account_sid or not auth_token or not from_number:
            return None
        return cls(account_sid, auth_token, from_number)

    def place_call(self, number: str) -> str:
        response = self._client.calls.create(
            to=number,
            from_=self._from_number,
            twiml=(
                "<Response>"
                '<Say language="pt-BR">Esta é uma chamada de teste autorizada.</Say>'
                '<Pause length="30"/>'
                "</Response>"
            ),
        )
        return response.sid

    def wait_for_completion(
        self, call_id: str, stop_event: threading.Event, update: Callable[[str], None]
    ) -> str:
        while not stop_event.is_set():
            call = self._client.calls(call_id).fetch()
            status = str(call.status)
            update(f"status Twilio: {status}")
            if status in TERMINAL_STATUSES:
                return status
            stop_event.wait(2)
        self.cancel_call(call_id)
        return "canceled"

    def cancel_call(self, call_id: str) -> None:
        try:
            self._client.calls(call_id).update(status="canceled")
        except Exception:
            # The worker still stops locally if the provider already finished.
            pass


class DialerController:
    """One-number-at-a-time worker with a cooperative stop signal."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._provider: CallProvider | None = None
        self._current_call_id: str | None = None
        self._state: dict[str, Any] = self._new_state()

    @staticmethod
    def _new_state() -> dict[str, Any]:
        return {
            "running": False,
            "status": "Parado",
            "total": 0,
            "processed": 0,
            "current_number": "",
            "current_attempt": 0,
            "max_attempts": 0,
            "logs": [],
        }

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._state["running"])

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["logs"] = [dict(entry) for entry in self._state["logs"]]
            return state

    def start(
        self,
        numbers: list[str],
        provider: CallProvider,
        max_attempts: int,
        retry_seconds: int,
    ) -> None:
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("O discador já está em execução.")
            self._stop_event.clear()
            self._provider = provider
            self._state = self._new_state()
            self._state.update(
                {
                    "running": True,
                    "status": "Iniciando",
                    "total": len(numbers),
                    "max_attempts": max_attempts,
                }
            )

        self._thread = threading.Thread(
            target=self._run,
            args=(numbers, max_attempts, retry_seconds),
            daemon=True,
            name="phone-dialer-worker",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            call_id = self._current_call_id
            provider = self._provider
            if self._state["running"]:
                self._state["status"] = "Parando..."
        if call_id and provider:
            provider.cancel_call(call_id)

    def _append_log(self, number: str, attempt: int, status: str, detail: str = "") -> None:
        entry = CallLogEntry(
            timestamp=datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M:%S"),
            number=number,
            attempt=attempt,
            status=status,
            detail=detail,
        )
        with self._lock:
            self._state["logs"].insert(0, asdict(entry))
            self._state["logs"] = self._state["logs"][:200]

    def _set_progress(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    def _run(self, numbers: list[str], max_attempts: int, retry_seconds: int) -> None:
        provider = self._provider
        if provider is None:
            return

        try:
            for index, number in enumerate(numbers):
                if self._stop_event.is_set():
                    break

                self._set_progress(
                    current_number=number,
                    current_attempt=0,
                    status=f"Preparando {number}",
                )

                for attempt in range(1, max_attempts + 1):
                    if self._stop_event.is_set():
                        break

                    self._set_progress(
                        current_number=number,
                        current_attempt=attempt,
                        status=f"Ligando para {number}",
                    )
                    try:
                        call_id = provider.place_call(number)
                        with self._lock:
                            self._current_call_id = call_id
                        self._append_log(number, attempt, "iniciada", f"id: {call_id}")

                        final_status = provider.wait_for_completion(
                            call_id,
                            self._stop_event,
                            lambda message: self._set_progress(status=message),
                        )
                        self._append_log(number, attempt, final_status)
                    except Exception as error:
                        final_status = "erro"
                        self._append_log(number, attempt, final_status, str(error))
                    finally:
                        with self._lock:
                            self._current_call_id = None

                    if self._stop_event.is_set() or final_status == "completed":
                        break

                    if attempt < max_attempts and final_status in RETRYABLE_STATUSES | {"erro"}:
                        self._set_progress(
                            status=f"Retentando {number} em {retry_seconds}s"
                        )
                        if self._stop_event.wait(retry_seconds):
                            break

                self._set_progress(processed=index + 1)

            stopped = self._stop_event.is_set()
            self._set_progress(
                running=False,
                status="Parado pelo usuário" if stopped else "Concluído",
                current_number="",
                current_attempt=0,
            )
        except Exception as error:
            self._append_log("", 0, "erro interno", str(error))
            self._set_progress(running=False, status="Erro interno")
        finally:
            with self._lock:
                self._current_call_id = None


CONTROLLER = DialerController()

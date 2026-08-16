from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import streamlit as st

#from dialer import CONTROLLER, DemoProvider, TwilioProvider, parse_phone_list


PROJECT_DIR = Path(__file__).parent


def make_download_bundle() -> bytes:
    """Create a self-contained zip without including any secret or local state."""
    files = [
        PROJECT_DIR / "app.py",
        PROJECT_DIR / "dialer.py",
        PROJECT_DIR / "requirements.txt",
        PROJECT_DIR / "README.md",
        PROJECT_DIR / ".streamlit" / "config.toml",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, file_path.relative_to(PROJECT_DIR.parent))
    return buffer.getvalue()

"""
def get_provider(mode: str):
    if mode == "Demonstração (não faz chamadas)":
        return DemoProvider(), True
    provider = TwilioProvider.from_environment()
    return provider, provider is not None
"""

def render_live_status() -> None:
   # state = CONTROLLER.snapshot()
    st.subheader("Acompanhamento")
    columns = st.columns(4)
    columns[0].metric("Estado", state["status"])
    columns[1].metric("Números", f'{state["processed"]}/{state["total"]}')
    columns[2].metric("Número atual", state["current_number"] or "—")
    columns[3].metric("Tentativa", state["current_attempt"] or "—")

    if state["total"]:
        st.progress(min(state["processed"] / state["total"], 1.0))

    if state["logs"]:
        st.dataframe(
            state["logs"],
            use_container_width=True,
            hide_index=True,
            column_config={
                "timestamp": "Horário",
                "number": "Número",
                "attempt": "Tentativa",
                "status": "Resultado",
                "detail": "Detalhe",
            },
        )
    else:
        st.info("As tentativas aparecerão aqui.")


@st.fragment(run_every=2)
def live_status_fragment() -> None:
    #render_live_status()


#st.set_page_config(page_title="Discador de lista", page_icon="☎️", layout="wide")
st.title("Discador de lista")
st.write(
    "Importe um arquivo .txt, revise os números e controle chamadas sequenciais "
    "em um único lugar."
)

st.warning(
    "Use somente números de pessoas que autorizaram o contato e respeite as leis "
    "locais, regras de telemarketing e os termos do seu provedor."
)

with st.sidebar:
    st.header("Configuração")
    region = st.selectbox(
        "País padrão dos números sem +",
        options=["BR", "US", "PT", "AR", "CL", "CO"],
        index=0,
        help="Exemplo: 11987654321 será interpretado como Brasil quando BR estiver selecionado.",
    )
    mode = st.selectbox(
        "Modo de operação",
        ["Demonstração (não faz chamadas)", "Twilio (chamadas reais)"],
    )
    max_attempts = st.slider(
        "Máximo de tentativas por número",
        min_value=1,
        max_value=10,
        value=3,
        help="Limite de segurança para evitar chamadas repetidas sem controle.",
    )
    retry_seconds = st.slider(
        "Espera antes de repetir (segundos)",
        min_value=30,
        max_value=300,
        value=60,
        step=30,
    )

    if mode == "Twilio (chamadas reais)":
        if TwilioProvider.from_environment() is None:
            st.error(
                "Twilio ainda não está conectado/configurado. Conecte o Twilio e "
                "adicione as variáveis indicadas no README."
            )
        else:
            st.success("Twilio configurado.")
    else:
        st.info("Este modo só simula o ciclo e não telefona para ninguém.")

uploaded = st.file_uploader(
    "Anexe a lista de telefones",
    type=["txt"],
    help="Um número por linha. Linhas vazias e linhas começando com # são ignoradas.",
)

records = []
if uploaded is not None:
    try:
        content = uploaded.getvalue().decode("utf-8-sig")
        records = parse_phone_list(content, region)
        st.session_state["last_file_name"] = uploaded.name
        st.session_state["phone_records"] = records
    except UnicodeDecodeError:
        st.error("Não consegui ler o arquivo. Salve o .txt em UTF-8 e tente novamente.")
else:
    records = st.session_state.get("phone_records", [])

if records:
    valid_numbers = [record.normalized for record in records if record.valid and record.normalized]
    invalid_count = len(records) - len(valid_numbers)
    st.subheader("Números encontrados")
    st.caption(
        f"Arquivo: {st.session_state.get('last_file_name', 'lista')} · "
        f"{len(valid_numbers)} válidos · {invalid_count} para revisar"
    )
    st.dataframe(
        [
            {
                "Original": record.original,
                "Número normalizado": record.normalized or "—",
                "Situação": "Válido" if record.valid else f"Inválido: {record.error}",
            }
            for record in records
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    valid_numbers = []
    st.info("Anexe um arquivo .txt para começar.")

consent = st.checkbox(
    "Confirmo que tenho autorização para contatar todos os números válidos desta lista."
)

#provider, provider_ready = get_provider(mode)
start_col, stop_col = st.columns(2)
with start_col:
    start_disabled = (
        not valid_numbers
        or not consent
        or CONTROLLER.is_running()
        or not provider_ready
    )
    if st.button("Iniciar", type="primary", use_container_width=True, disabled=start_disabled):
        CONTROLLER.start(
            valid_numbers,
            provider,
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        st.rerun()
with stop_col:
    if st.button(
        "Parar imediatamente",
        use_container_width=True,
       # disabled=not CONTROLLER.is_running(),
    ):
        CONTROLLER.stop()
        st.rerun()

#if CONTROLLER.is_running():
  #  st.info("O discador está ativo. Use “Parar imediatamente” quando quiser encerrar.")

live_status_fragment()

st.divider()
st.subheader("Baixar o código")
st.write(
    "O pacote inclui a interface, o controlador de tentativas, o adaptador Twilio, "
    "dependências e um guia de instalação."
)
st.download_button(
    "Baixar projeto .zip",
    data=make_download_bundle(),
    file_name="discador-streamlit.zip",
    mime="application/zip",
)

with st.expander("Como preparar uma lista"):
    st.code("# comentários são ignorados\n+5511999999999\n+351912345678\n11988887777")

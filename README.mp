# Discador de lista com Streamlit

Aplicação simples para carregar um `.txt` com um telefone por linha, validar os
números e executar um fluxo sequencial de chamadas.

## Importante

Use apenas com pessoas que autorizaram o contato. Ligações automatizadas podem
ser reguladas por leis locais, regras de telemarketing e pelos termos do
provedor telefônico.

O programa começa em **modo demonstração**, que não faz ligações. O código
também possui um adaptador para Twilio, mas chamadas reais só ficam disponíveis
quando o Twilio estiver conectado e configurado.

Para manter o uso sob controle, a interface exige:

- confirmação de que os destinatários autorizaram o contato;
- processamento de um número por vez;
- limite de 1 a 10 tentativas por número;
- espera mínima de 30 segundos entre tentativas;
- botão de parada imediata.

## Como usar no Replit

1. Execute a aplicação pelo workflow configurado ou rode:

   ```bash
   streamlit run app.py --server.port 5000
   ```

2. Anexe um arquivo `.txt` com um número por linha.
3. Escolha o país padrão para linhas sem o prefixo `+`.
4. Primeiro use **Demonstração** para conferir o fluxo.
5. Marque a confirmação de autorização.
6. Clique em **Iniciar** e acompanhe o histórico.
7. Clique em **Parar imediatamente** para encerrar o processamento.

Linhas vazias e linhas iniciadas por `#` são ignoradas. Números válidos são
convertidos para o formato internacional E.164.

## Ativar chamadas reais com Twilio

O usuário precisa conectar/autorizar o Twilio e ter um número Twilio habilitado
para fazer chamadas. Depois, o ambiente deve disponibilizar estas variáveis
como secrets:

```text
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER
```

Nunca coloque os valores no código, no arquivo `.txt` ou no README. A aplicação
lê essas variáveis somente em tempo de execução.

No modo Twilio, cada chamada executa uma mensagem curta em português e espera
até 30 segundos. Se o status for `busy`, `failed`, `no-answer` ou `canceled`,
ela pode ser repetida até o limite configurado. O botão de parada também tenta
cancelar a chamada que estiver ativa.

## Executar fora do Replit

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py --server.port 5000
```

Configure as três variáveis do Twilio no ambiente antes de escolher o modo
Twilio.

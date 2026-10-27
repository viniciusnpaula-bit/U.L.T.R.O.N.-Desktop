# ULTRON Protected AI Gateway

Este serviço mantém a chave Groq exclusivamente no servidor. O APK nunca deve conter a chave Groq.

## Executar localmente

Requer Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# Configure GROQ_API_KEY e ULTRON_API_TOKEN no ambiente do processo; não comite um arquivo .env real.
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Configure `GROQ_API_KEY`, `ULTRON_API_TOKEN` e (opcionalmente) `RATE_LIMIT_REQUESTS` como secrets/environment variables no serviço de hospedagem. Use HTTPS em produção. Não exponha o servidor de desenvolvimento diretamente à internet. O limite por IP em memória é uma proteção básica; em produção com múltiplas instâncias, configure rate limiting no gateway/provedor e monitore custos.

`ULTRON_API_TOKEN` é obrigatório: sem ele o serviço responde 503 e não atende ninguém. Gere um valor aleatório e o configure também no build do APK (`-PULTRON_AI_TOKEN=...`). O token fica embutido no APK e é extraível por quem tiver o binário, então mantenha também um limite de gasto no painel da Groq.

## Contrato

- `GET /health`: status mínimo e indicação booleana se o segredo está configurado; não revela a chave.
- `POST /v1/chat`: exige o header `X-Ultron-Token` igual a `ULTRON_API_TOKEN`; sem ele responde 401.
- `POST /v1/chat`: JSON com `message` e até 12 mensagens de histórico (`role`: `user` ou `assistant`). Retorna `reply` e `model`.
- Mensagem: até 4.000 caracteres; timeout upstream; erros upstream não são repassados em bruto.

## Testes

```bash
pip install -r requirements.txt
pytest -q
```

Este PR fornece o serviço e o adaptador Android. A IA online só funcionará depois que o backend for implantado com a secret e a URL HTTPS configuradas no build do aplicativo.
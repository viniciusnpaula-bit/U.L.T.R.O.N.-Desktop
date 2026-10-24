# Política de Segurança

## Versões suportadas

| Versão | Suportada |
|--------|-----------|
| >= 1.9.9 | ✅ Sim |
| < 1.9.9 | ❌ Não |

Versões anteriores à 1.9.9 não recebem correções de segurança porque não possuem validação de assinatura Ed25519 nas atualizações.

## Reportando uma vulnerabilidade

Se você encontrou uma vulnerabilidade de segurança, **não abra um issue público**.

Envie um e-mail para: **[seu-email]@exemplo.com**

Inclua o máximo de detalhes possível:
- Descrição da vulnerabilidade
- Passos para reproduzir
- Versão do ULTRON afetada
- Impacto potencial
- Sugestão de correção (opcional)

## Escopo

Dentro do escopo:
- Execução remota de código através da IA ou comandos de voz
- Bypass da confirmação/PIN para ações sensíveis (`teclado.py`, `cofre.py`, etc.)
- Vazamento da `GEMINI_API_KEY` ou outros segredos armazenados localmente
- Bypass da validação de assinatura Ed25519 nas atualizações automáticas

Fora do escopo:
- Engenharia social para obter a chave de IA do usuário
- Ataques físicos na máquina do usuário
- Vulnerabilidades em dependências de terceiros não diretamente usadas pelo ULTRON

## Resposta

Tentaremos confirmar o recebimento do seu relatório em até **72 horas** e fornecer uma previsão de correção em até **7 dias**.

## Agradecimentos

Agradecemos a pesquisadores de segurança que reportam de boa fede e seguem esta política.

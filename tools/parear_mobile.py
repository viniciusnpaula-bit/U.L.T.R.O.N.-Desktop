"""Gerenciamento de pareamento LAN e servidor ponte para o U.L.T.R.O.N. Mobile.

Exemplos:
    python tools/parear_mobile.py --gerar --device-id galaxy-a34
    python tools/parear_mobile.py --mostrar
    python tools/parear_mobile.py --firewall
    python tools/parear_mobile.py --servir
    python tools/parear_mobile.py --revogar
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import mobile_api  # noqa: E402
import mobile_pairing  # noqa: E402


def _imprimir_pareamento(dados: dict) -> None:
    print("=" * 68)
    print("U.L.T.R.O.N. Desktop <-> Mobile (Pareamento LAN HMAC-SHA256)")
    print("=" * 68)
    print(f"URL LAN do Desktop : {dados['lan_url']}")
    print(f"Device ID          : {dados['device_id']}")
    print(f"Shared Secret      : {dados['shared_secret']}")
    print(f"URL Kill Switch    : {dados['killswitch_url']}")
    if dados["killswitch_separado"]:
        print(f"Segredo KillSwitch : {dados['killswitch_secret']}")
    else:
        print("Segredo KillSwitch : (mesmo Shared Secret acima)")
    print("-" * 68)
    print("Guarde o Shared Secret no aplicativo Mobile agora (tela Pareamento LAN).")
    print("Ele não será exibido novamente por --mostrar.")
    print("=" * 68)


def _imprimir_status() -> int:
    st = mobile_pairing.status_publico()
    print(f"Pareamento ativo : {'SIM' if st['configured'] else 'NÃO (fail-closed)'}")
    print(f"URL LAN sugerida : {st['lan_url']}")
    print(f"URL Kill Switch  : {st['killswitch_url']}")
    if st["devices"]:
        print("Dispositivos pareados:")
        for d in st["devices"]:
            print(f"  - {d['device_id']} (segredo: {d['hint']})")
    else:
        print("Dispositivos pareados: nenhum")
    if st["killswitch_dedicated"]:
        print(f"Segredo KillSwitch dedicado: {st['killswitch_hint']}")
    return 0


def _imprimir_firewall(porta: int) -> int:
    print("# Execute em um PowerShell como Administrador para liberar a porta apenas na rede Privada (LAN):")
    print(
        f'New-NetFirewallRule -DisplayName "ULTRON Mobile LAN Bridge" '
        f'-Direction Inbound -Protocol TCP -LocalPort {int(porta)} '
        f'-Profile Private -Action Allow'
    )
    return 0


def _servir(host: str | None, port: int | None) -> int:
    if not mobile_pairing.tem_pareamento_ativo():
        print(
            "ERRO (fail-closed): nenhum pareamento ativo configurado.\n"
            "Execute primeiro: python tools/parear_mobile.py --gerar --device-id galaxy-a34"
        )
        return 1
    server, lan_url = mobile_api.create_mobile_server(host=host, port=port)
    print(f"Servidor LAN do U.L.T.R.O.N. Mobile escutando em {lan_url}")
    print("Endpoints: POST /api/mobile/command | POST /killswitch")
    print("Pressione Ctrl+C para encerrar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor LAN...")
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    acao = parser.add_mutually_exclusive_group()
    acao.add_argument("--mostrar", action="store_true", help="exibe status e URL LAN (sem segredos)")
    acao.add_argument("--gerar", action="store_true", help="gera ou rotaciona credenciais de pareamento")
    acao.add_argument("--rotacionar", action="store_true", help="alias para --gerar")
    acao.add_argument("--revogar", action="store_true", help="revoga um dispositivo ou todo o pareamento")
    acao.add_argument("--firewall", action="store_true", help="imprime regra de Firewall Windows (Perfil Private)")
    acao.add_argument("--servir", action="store_true", help="sobe o servidor LAN standalone até Ctrl+C")
    parser.add_argument("--device-id", default=None, help="identificador do aparelho (ex: galaxy-a34)")
    parser.add_argument(
        "--killswitch-separado",
        action="store_true",
        help="gera um segredo exclusivo para o Kill Switch em vez de compartilhar o segredo do pareamento",
    )
    parser.add_argument("--host", default=None, help="endereço de bind para --servir")
    parser.add_argument("--port", type=int, default=None, help="porta TCP para --servir")

    args = parser.parse_args()
    if args.gerar or args.rotacionar:
        dados = mobile_pairing.criar_ou_rotacionar(
            device_id=args.device_id,
            killswitch_separado=args.killswitch_separado,
        )
        _imprimir_pareamento(dados)
        return 0
    if args.revogar:
        res = mobile_pairing.revogar(device_id=args.device_id)
        print(f"Pareamento revogado ({res['removed_count']} item(ns) removido(s)).")
        return 0
    if args.firewall:
        return _imprimir_firewall(args.port or config.MOBILE_PORT)
    if args.servir:
        return _servir(args.host, args.port)
    return _imprimir_status()


if __name__ == "__main__":
    raise SystemExit(main())

"""Inicie o Agente SCD com: uv run app.py."""
import argparse

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Agente SCD — análises e relatórios")
    parser.add_argument('--host', default='127.0.0.1', help='Interface de rede (padrão: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8080, help='Porta HTTP (padrão: 8080)')
    parser.add_argument('--reload', action='store_true', help='Recarregar código durante desenvolvimento')
    args = parser.parse_args()
    uvicorn.run('api.main:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()

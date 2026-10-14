"""Stable user commands, usable from the source tree or installed launcher."""
import argparse
import json
import sys
import subprocess


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dictate')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['doctor', 'status']:
        commands.add_parser(name).add_argument('--json', action='store_true')
    commands.add_parser('install').add_argument('--extension-id', required=True)
    commands.add_parser('update').add_argument('--source', required=True, help='克隆仓库或解压发布包的根目录')
    commands.add_parser('uninstall')
    args = parser.parse_args(argv)
    try:
        if args.command in ['doctor', 'status']:
            from .doctor import report, installed_status
            data = report() if args.command == 'doctor' else installed_status()
            if args.json:
                print(json.dumps(data, ensure_ascii=False))
            else:
                if args.command == 'doctor':
                    for c in data['checks']:
                        label = 'OK' if c['ok'] else ('FAIL' if c['required'] else 'OPTIONAL')
                        print(f'[{label}] {c["name"]}' + ('' if c['ok'] else ': ' + c['detail']))
                    print(data['next'])
                print(json.dumps(data.get('service', data), ensure_ascii=False))
            return 0 if args.command == 'status' or data['ok'] else 1
        from . import install
        if args.command == 'install':
            install.install(args.extension_id)
        elif args.command == 'update':
            from pathlib import Path
            source = Path(args.source).resolve() / 'native/dictate'
            if not (source / 'daemon.py').is_file():
                raise ValueError('source 不是 dictate 项目或发布包根目录。')
            install.SOURCE = source
            install.update()
        else:
            install.uninstall()
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

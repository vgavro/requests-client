import logging

import coloredlogs
import click
import IPython

from requests_client.utils import import_string


@click.command()
@click.argument('client_cls')
@click.argument('config', required=False, type=click.Path(exists=True))
@click.option('--loglevel', default=1, type=int)
def main(client_cls=None, config=None, loglevel=1):
    # TODO: add autoreload turned off by default

    coloredlogs.DEFAULT_FIELD_STYLES['asctime'] = {'color': 'magenta'}
    coloredlogs.install(level=loglevel, datefmt='%H:%M:%S',
                        fmt='%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s')

    # Turn off verbose debugs on ipython autocomplete
    logging.getLogger('parso').propagate = False

    client_cls = import_string(client_cls)
    client = client_cls.create_from_config(config)  # noqa
    from requests_client.utils import pprint  # noqa
    IPython.embed()


if __name__ == '__main__':
    # You can import main and use like this:
    # myclient/__main__.py
    # from requests_client.__main__ import main
    # from sys import argv
    # main(['myclient.MyClient'] + argv[1:])
    # To get to interactive shell create config "my.yaml" and run "python ./myclient"

    main()

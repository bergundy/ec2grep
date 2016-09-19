#!/usr/bin/env python
from concurrent.futures import wait, ThreadPoolExecutor as Executor
from functools import partial
from operator import itemgetter

import os
import sys
import click
import boto3
import itertools
import six

executor = Executor(4)
name = (lambda i: {tag['Key']: tag['Value'] for tag in i.get('Tags', [])}.get('Name', ''))
public_ip = itemgetter('PublicIpAddress')
private_ip = itemgetter('PrivateIpAddress')
extended_public = (lambda i: "{} ({})".format(name(i), public_ip(i)))
extended_private = (lambda i: "{} ({})".format(name(i), private_ip(i)))
DEFAULT_ATTRIBUTES = [
    'tag:Name',
    'network-interface.addresses.association.public-ip',
    'network-interface.addresses.private-ip-address',
    'network-interface.private-dns-name'
]


def _get_instances(ec2, filter_):
    response = ec2.describe_instances(Filters=[filter_])
    reservations = response['Reservations']
    return list(itertools.chain.from_iterable(r['Instances'] for r in reservations))


def match_instances(region_name, query, attributes=DEFAULT_ATTRIBUTES):
    ec2 = boto3.client('ec2', region_name=region_name)
    get_instances = partial(_get_instances, ec2)
    instance_lists = executor.map(get_instances, [
        {'Name': attr, 'Values': ['*{}*'.format(query)]} for attr in attributes
    ])
    chained = (i for i in itertools.chain.from_iterable(instance_lists) if public_ip(i))
    return sorted(chained, key=name)


def die(*args):
    click.echo(*args, err=True)
    sys.exit(1)


def read_number(min_value, max_value):
    while True:
        try:
            choice = six.moves.input()
            choice = int(choice)
            if not (min_value <= choice <= max_value):
                raise ValueError("Invalid input")
            return choice
        except ValueError as e:
            click.echo("{}".format(e), err=True)
            continue


formatters = {
    'extended_public': extended_public,
    'extended_private': extended_private,
    'public_ip': public_ip,
    'private_ip': private_ip,
    'name': name
}


@click.group()
@click.option('--region', '-r', default='us-east-1')
@click.pass_context
def cli(ctx, region):
    ctx.obj = {'region': region}


@cli.command()
@click.option('--key', '-i')
@click.option('--prefer-private-ip', '-p', is_flag=True, default=False)
@click.argument('query')
@click.argument('ssh_args', nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ssh(ctx, key, prefer_private_ip, query, ssh_args):
    get_ip = private_ip if prefer_private_ip else public_ip
    fmt_match = extended_private if prefer_private_ip else extended_public
    extra_args = []

    matches = match_instances(ctx.obj['region'], query)
    if not matches:
        die("No matches found")

    if len(matches) > 1:
        for i, inst in enumerate(matches):
            click.echo("[{}] {}".format(i+1, fmt_match(inst)))
        click.echo("pick an option [1-{}] ".format(len(matches)), nl=False)
        index = read_number(1, len(matches)) - 1
        choice = matches[index]
        click.echo("")
    else:
        choice = matches[0]

    click.echo("sshing {}".format(fmt_match(choice)))

    if key:
        extra_args.extend(['-i', key])
    os.execvp('ssh', ['ssh', '-oStrictHostKeyChecking=no'] + extra_args + [get_ip(choice)] + list(ssh_args))


@cli.command()
@click.argument('query')
@click.option('--delim', '-d', default='\n')
@click.option('--formatter', '-f', default='extended_public')
@click.option('--custom-format', '-c', is_flag=True, default=False)
@click.pass_context
def ls(ctx, query, formatter, delim, custom_format):
    matches = match_instances(ctx.obj['region'], query)
    if not custom_format:
        formatter = formatter.join('{}')
    if not matches:
        die("No matches found")

    click.echo(delim.join(formatter.format(**{k: f(m) for k, f in formatters.iteritems()}) for m in matches))


if __name__ == '__main__':
    cli()

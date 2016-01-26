#!/usr/bin/env python
from __future__ import print_function
from concurrent.futures import wait, ThreadPoolExecutor as Executor
from functools import partial

import os
import sys
import click
import boto3
import itertools
import six

executor = Executor(4)
name = lambda i: {tag['Key']: tag['Value'] for tag in i.get('Tags', [])}.get('Name', '')
ip = lambda i: i.get('PublicIpAddress', 'no-ip')
fmt = lambda i: "{} ({})".format(name(i), ip(i))
DEFAULT_ATTRIBUTES = ['tag:Name', 'network-interface.addresses.association.public-ip', 'network-interface.addresses.private-ip-address', 'network-interface.private-dns-name']


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
    return list(itertools.chain.from_iterable(instance_lists))


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


@click.group()
@click.option('--region', '-r', default='us-east-1')
@click.pass_context
def cli(ctx, region):
    ctx.obj = {'region': region}


@cli.command()
@click.argument('query')
@click.argument('ssh_args', nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ssh(ctx, query, ssh_args):
    matches = match_instances(ctx.obj['region'], query)
    if not matches:
        die("No matches found")

    if len(matches) > 1:
        for i, inst in enumerate(matches):
            click.echo("[{}] {}".format(i+1, fmt(inst)))
        click.echo("pick an option [1-{}] ".format(len(matches)), nl=False)
        index = read_number(1, len(matches)) - 1
        choice = matches[index]
        click.echo("")
    else:
        choice = matches[0]

    if 'PublicIpAddress' not in choice:
        die("No public ip address")

    click.echo("sshing {}".format(fmt(choice)))
    os.execvp('ssh', ['ssh'] + [choice['PublicIpAddress']] + list(ssh_args))


@cli.command()
@click.argument('query')
@click.option('--formatter', '-f', type=click.Choice(['extended', 'ip', 'name']), default='extended')
@click.pass_context
def ls(ctx, query, formatter):
    matches = match_instances(ctx.obj['region'], query)
    formatter = {'extended': fmt, 'ip': ip, 'name': name}[formatter]
    if not matches:
        die("No matches found")

    for m in matches:
        click.echo("{}".format(formatter(m)))


if __name__ == '__main__':
    cli()

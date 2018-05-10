#! /usr/bin/env python

import concurrent.futures
import functools
import itertools
import operator
import pprint
import subprocess
import sys
import threading

import boto3
import click
import six


DEFAULT_ATTRIBUTES = (
    'tag:Name',
    'network-interface.addresses.association.public-ip',
    'network-interface.addresses.private-ip-address',
    'network-interface.private-dns-name',
)


name = (lambda i: {tag['Key']: tag['Value'] for tag in i.get('Tags', [])}.get('Name', ''))
public_ip = operator.itemgetter('PublicIpAddress')
private_ip = operator.itemgetter('PrivateIpAddress')
extended_public = (lambda i: '{} ({})'.format(name(i), public_ip(i)))
extended_private = (lambda i: '{} ({})'.format(name(i), private_ip(i)))
extended = (lambda i: '{} (public: {}, private: {})'.format(name(i), public_ip(i), private_ip(i)))
formatters = {
    'extended': extended,
    'extended_public': extended_public,
    'extended_private': extended_private,
    'public_ip': public_ip,
    'private_ip': private_ip,
    'name': name,
}


@click.group()
@click.option('--region', '-r', default='us-east-1')
@click.pass_context
def cli(ctx, region):
    ctx.obj = {'region': region}


@cli.command()
@click.option('--key', '-i')
@click.option('--prefer-public-ip', '-p', is_flag=True, default=False)
@click.option('--parallel', is_flag=True, default=False)
@click.argument('query')
@click.argument('ssh_args', nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def ssh(ctx, key, prefer_public_ip, parallel, query, ssh_args):
    get_ip = public_ip if prefer_public_ip else private_ip
    fmt_match = extended_public if prefer_public_ip else extended_private
    matches = match_instances(ctx.obj['region'], query)
    if not matches:
        die('No matches found')
    if len(matches) > 1:
        click.echo('[0] All')
        for i, inst in enumerate(matches):
            click.echo('[{}] {}'.format(i+1, fmt_match(inst)))
        click.echo('select servers [0-{}] (comma separated) '.format(len(matches)), nl=False)
        indices = read_numbers(0, len(matches))
        if len(indices) == 1 and indices[0] == 0:
            choices = matches
        else:
            choices = [matches[index - 1] for index in indices]
        click.echo()
    else:
        choices = [matches[0]]
    command = ['ssh', '-oStrictHostKeyChecking=no']
    if key:
        command.extend(['-i', key])
    if parallel and len(choices) > 1:
        message = 'sshing:\n{}'.format(pprint.pformat([fmt_match(c) for c in choices]))
        click.echo(message)
        click.echo()
        processes = []
        for choice in choices:
            ip = get_ip(choice)
            p = subprocess.Popen(command + [ip] + list(ssh_args),
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
            stdout_consumer = OutputConsumer(input=p.stdout, output=sys.stdout, ip=ip)
            stderr_consumer = OutputConsumer(input=p.stderr, output=sys.stderr, ip=ip)
            processes.append({'out': stdout_consumer, 'err': stderr_consumer, 'p': p})
        for p in processes:
            p['p'].wait()
            p['out'].join()
            p['err'].join()
    else:
        for choice in choices:
            message = 'sshing {}'.format(fmt_match(choice))
            click.echo()
            click.echo(message)
            click.echo(u'\u2500' * len(message))
            subprocess.call(command + [get_ip(choice)] + list(ssh_args))


@cli.command()
@click.option('--delim', '-d', default='\n')
@click.option('--formatter', '-f', default='extended_private')
@click.option('--custom-format', '-c', is_flag=True, default=False)
@click.argument('query')
@click.pass_context
def ls(ctx, formatter, delim, custom_format, query):
    matches = match_instances(ctx.obj['region'], query)
    if not matches:
        die('No matches found')
    if not custom_format:
        formatter = formatter.join('{}')
    click.echo(delim.join(formatter.format(**{k: f(m) for k, f in formatters.iteritems()}) for m in matches))


def _get_instances(ec2, filter_):
    response = ec2.describe_instances(Filters=[filter_])
    reservations = response['Reservations']
    return list(itertools.chain.from_iterable(r['Instances'] for r in reservations))


def match_instances(region_name, query, attributes=DEFAULT_ATTRIBUTES):
    ec2 = boto3.client('ec2', region_name=region_name)
    get_instances = functools.partial(_get_instances, ec2)
    with concurrent.futures.ThreadPoolExecutor(len(attributes)) as executor:
        instance_lists = executor.map(get_instances, [
            {'Name': attr, 'Values': ['*{}*'.format(query)]} for attr in attributes
        ])
    chained = (i for i in itertools.chain.from_iterable(instance_lists) if 'PublicIpAddress' in i)
    return sorted(chained, key=name)


def die(*args):
    click.echo(*args, err=True)
    sys.exit(1)


def read_numbers(min_value, max_value):
    while True:
        try:
            choices = six.moves.input()
            choices = [int(c.strip()) for c in choices.split(',')]
            if not (all(min_value <= c <= max_value for c in choices)):
                raise ValueError('Invalid input')
            if len(choices) != 1 and 0 in choices:
                raise ValueError('Invalid input')
            return choices
        except ValueError as e:
            click.echo(str(e), err=True)
            continue


class OutputConsumer(object):

    def __init__(self, input, output, ip):
        self.ip = ip
        self.input = input
        self.output = output
        self.consumer = threading.Thread(target=self.consume_output)
        self.consumer.daemon = True
        self.consumer.start()

    def consume_output(self):
        for line in iter(self.input.readline, b''):
            self.output.write('[{:<15}] {}'.format(self.ip, line))

    def join(self):
        self.consumer.join()


if __name__ == '__main__':
    cli()

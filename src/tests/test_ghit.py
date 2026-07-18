import argparse

import pytest

from ghit.ghit import add_stack_commands, add_top_commands, apply_common_defaults, create_common_parser


def _parse(argv):
    common = create_common_parser()
    parser = argparse.ArgumentParser(parents=[common])
    commands = add_top_commands(parser, common)
    add_stack_commands(commands.add_parser('stack', aliases=['s', 'st'], parents=[common]), common)
    args = parser.parse_args(argv)
    apply_common_defaults(args)
    return args


def test_flags_before_subcommand():
    args = _parse(['-o', '-v', 'stack', 'check'])
    assert args.offline is True
    assert args.verbose is True


def test_flags_after_subcommand():
    args = _parse(['stack', 'check', '-o', '-v'])
    assert args.offline is True
    assert args.verbose is True


def test_repository_before_subcommand():
    args = _parse(['-r', '/some/path', 'ls'])
    assert args.repository == '/some/path'


@pytest.mark.parametrize('argv', [['ls'], ['stack', 'check']])
def test_defaults_applied(argv):
    args = _parse(argv)
    assert args.offline is False
    assert args.verbose is False
    assert args.debug is False
    assert args.repository == '.'
    assert args.stack is None

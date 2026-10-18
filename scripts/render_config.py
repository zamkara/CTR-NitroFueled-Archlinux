# SPDX-License-Identifier: GPL-2.0-or-later
"""Resolve the same render plan for the Linux launcher and restart path."""
import argparse
from pathlib import Path
from patches import read_settings, render_plan


def configuration(settings, neo='0', memory='0'):
    plan = render_plan(settings)
    if not plan:
        return str(neo), str(memory or '0'), 'Game default'
    memory = int(memory or '0')
    if plan['heap']:
        memory = max(memory, 7168)
    return ('1' if plan['pro'] else '0'), str(memory), plan['label']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings', required=True, type=Path)
    p.add_argument('--neo', default='0')
    p.add_argument('--memory', default='0')
    a = p.parse_args()
    print('\t'.join(configuration(read_settings(a.settings), a.neo, a.memory)))

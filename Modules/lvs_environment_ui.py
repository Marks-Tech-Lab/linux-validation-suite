"""Standard-library presentation for the standalone Linux environment manager.

No terminal probes, external commands or environment changes occur here.
Keep bootstrap compatibility with Python 3.6 syntax.
"""
import os
import re
import shutil
import sys


def plain_text(value):
    text=re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', str(value))
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or ord(c)>=32 and ord(c)!=127)


class CustomizeEnvironment(Exception):
    """Return from an unapproved review to optional settings, before any work."""


class EnvironmentScreens:
    def __init__(self, ask=input, output=print, stdin=None, stdout=None, environ=None):
        self.ask=ask;self.output=output
        self.stdin=stdin if stdin is not None else sys.stdin
        self.stdout=stdout if stdout is not None else sys.stdout
        self.environ=environ if environ is not None else os.environ
        self.awaiting_ack=False

    def can_clear(self):
        term=self.environ.get('TERM','').lower()
        try:interactive=self.stdin.isatty() and self.stdout.isatty()
        except (AttributeError,OSError):interactive=False
        return (interactive
                and 'NO_COLOR' not in self.environ and term not in ('','dumb','unknown')
                and term.startswith(('xterm','screen','tmux','linux','vt100','vt220',
                                     'rxvt','ansi','alacritty','foot','wezterm','st-')))

    def write(self, value=''):
        self.output(plain_text(value))

    def open(self, title):
        if self.awaiting_ack:
            raise RuntimeError('Results must be acknowledged before opening another screen')
        if self.can_clear():self.output('\x1b[2J\x1b[H')
        self.write('\n'+title+'\n'+'='*len(title))

    def confirm(self, message, action='Continue with this operation', custom=False):
        self.write(message)
        self.write('1. '+action+'\n2. Cancel and return')
        if custom:self.write('3. Advanced settings (Python or local packages)')
        while True:
            choice=self.ask('Choose [2]: ').strip() or '2'
            if choice=='1':return True
            if choice=='2':return False
            if choice=='3' and custom:raise CustomizeEnvironment()
            self.write('Choose 1 or 2'+(', or 3 for advanced settings.' if custom else '.'))

    def details(self, text):
        lines=plain_text(text).splitlines() or ['No additional details.']
        page=max(8,min(40,shutil.get_terminal_size(fallback=(80,24)).lines-6))
        for offset in range(0,len(lines),page):
            self.write('\nTechnical details\n'+ '\n'.join(lines[offset:offset+page]))
            if offset+page<len(lines):
                if self.ask('Enter for more details, or 0 to return: ').strip()=='0':return

    def results(self, title, lines, details='', follow=None):
        # Do not clear on entry: output produced before an error stays visible.
        self.awaiting_ack=True
        self.write('\n'+title+'\n'+'-'*len(title))
        for line in lines:self.write(line)
        while True:
            self.write('\n1. Back to the menu\n2. Technical details')
            if follow:self.write('3. '+follow)
            try:
                choice=self.ask('Choose [1]: ').strip() or '1'
                if choice=='1':self.awaiting_ack=False;return 'back'
                if choice=='2':self.details(details)
                elif choice=='3' and follow:self.awaiting_ack=False;return 'follow'
                else:self.write('Choose one of the listed numbers.')
            except (EOFError,KeyboardInterrupt):
                self.write('\nResults left on screen. Closing the manager.')
                return 'exit'

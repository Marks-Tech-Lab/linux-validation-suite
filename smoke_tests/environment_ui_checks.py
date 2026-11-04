"""Presentation checks; no maintenance of the real development environment."""
import ast
import errno
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import lvs_environment_manager as em
from Modules.lvs_environment_ui import EnvironmentScreens, CustomizeEnvironment
from smoke_tests.environment_manager_checks import Fixture, ROOT
from smoke_tests.environment_wave1_checks import prepared


def terminal(value):
    return SimpleNamespace(isatty=lambda:value)


def display(f,answers,tty=False):
    iterator=iter(answers);prompts=[]
    def ask(prompt):prompts.append(prompt);return next(iterator)
    f.manager.ask=ask
    f.manager.screens=EnvironmentScreens(ask=ask,output=f.output.append,stdin=terminal(tty),stdout=terminal(tty),environ={'TERM':'xterm'})
    return prompts


def run_environment_ui_terminal_checks():
    for incoming,outgoing,env,expected in [
            (True,True,{'TERM':'xterm-256color'},True),
            (True,True,{'TERM':'dumb'},False),
            (True,True,{'TERM':'xterm','NO_COLOR':''},False),
            (False,True,{'TERM':'xterm'},False),(True,False,{'TERM':'xterm'},False),
            (False,False,{'TERM':'xterm'},False),(True,True,{},False),
            (True,True,{'TERM':'unrecognized-terminal'},False)]:
        output=[];screen=EnvironmentScreens(output=output.append,stdin=terminal(incoming),stdout=terminal(outgoing),environ=env)
        screen.open('Menu');screen.write('\x1b[31mExternal output\x1b[0m')
        assert any('\x1b' in line for line in output)==expected
        assert output[-1]=='External output'
    for name in ['lvs_environment_manager.py','Modules/lvs_environment_ui.py']:
        ast.parse((ROOT/name).read_text(),feature_version=(3,6))


def run_environment_ui_confirmation_checks():
    for response in ['', '2']:
        with TemporaryDirectory() as directory:
            f=Fixture(directory,confirm=response)
            assert f.manager.create_or_repair() is False
            assert not f.manager.venv.exists()
            assert not any('install' in args or 'venv' in args for args,_ in f.calls)
            assert not any('[y/N]' in line for line in f.output)
    answers=iter(['yes','']);screen=EnvironmentScreens(ask=lambda _:next(answers),output=lambda _:None)
    assert not screen.confirm('Change files') # old affirmative words cannot approve silently
    for interruption in (EOFError,KeyboardInterrupt):
        with TemporaryDirectory() as directory:
            f=Fixture(directory)
            def cancel(prompt):
                if prompt=='Choose [2]: ':raise interruption()
                return '1'
            f.manager.ask=cancel
            f.manager.run_screen('Set up environment',lambda:f.manager.guided_maintenance('repair'))
            assert not f.manager.venv.exists()
            assert not any('install' in args for args,_ in f.calls)
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();prompts=display(f,['1','1'])
        assert f.manager.run_screen('Repair environment',lambda:f.manager.guided_maintenance('repair'))=='back'
        assert sum(p=='Choose [2]: ' for p in prompts)==1
        assert not any('Python number' in p or 'Local wheel' in p for p in prompts)
        text='\n'.join(f.output)
        assert '1. Set up or repair Python environment' in text
        assert '"contract_id"' not in text and 'base_sha256' not in text and 'cpython-314-test' not in text
        assert 'Operation completed' in text


def run_environment_ui_results_checks():
    output=[];events=[]
    screen=EnvironmentScreens(output=output.append,stdin=terminal(True),stdout=terminal(True),environ={'TERM':'xterm'})
    screen.open('Operation')
    def acknowledge(prompt):
        events.append(prompt)
        assert any('Failed: keep the backup' in line for line in output)
        assert sum('\x1b[2J' in line for line in output)==1
        try:screen.open('Must not erase results')
        except RuntimeError:pass
        else:raise AssertionError('Unacknowledged results were erased')
        return ''
    screen.ask=acknowledge
    assert screen.results('Failed',['Failed: keep the backup'])=='back'
    screen.open('Menu');assert sum('\x1b[2J' in line for line in output)==2
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.fail_install=True;f.output.clear();display(f,['1','1'],tty=True)
        assert f.manager.run_screen('Package update',lambda:f.manager.guided_maintenance('sync'))=='back'
        text='\n'.join(f.output)
        assert 'Operation did not complete' in text and 'may be partial' in text and 'not been rolled back' in text
        assert 'repository unavailable' in text and 'Operation completed' not in text
        assert sum('\x1b[2J' in line for line in f.output)==1
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();prompts=display(f,['1','1'])
        f.manager.run_screen('Native helpers',lambda:f.manager.perform(lambda:f.manager.bridge(em.NATIVE,'Build helpers?')))
        assert sum(p=='Choose [2]: ' for p in prompts)==1
        assert 'existing integration invoked' not in '\n'.join(f.output)
        assert any(em.NATIVE in args and kwargs.get('stdout')==subprocess.PIPE for args,kwargs in f.calls)


def run_environment_ui_navigation_checks():
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();before=(f.manager.venv/'pyvenv.cfg').read_bytes()
        display(f,['3','5','4','3','8'],tty=True);f.manager.menu()
        assert sum(line=='\nLVS Environment Manager\n=======================' for line in f.output)==3
        assert sum('\x1b[2J' in line for line in f.output)==5
        assert (f.manager.venv/'pyvenv.cfg').read_bytes()==before
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();display(f,['','','8'])
        f.manager.menu();text='\n'.join(f.output)
        assert 'Health check finished' in text and '\x1b' not in text
        assert '"contract_id"' not in text
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear()
        def closed(_):raise EOFError()
        f.manager.ask=closed;f.manager.menu()
        assert any('Closing the manager' in line for line in f.output)
        f.manager.ask=lambda _:(_ for _ in ()).throw(KeyboardInterrupt());f.manager.menu()
        assert any('No further operation' in line for line in f.output)


def run_environment_ui_details_upgrade_checks():
    output=[];answers=iter(['2','1'])
    screen=EnvironmentScreens(ask=lambda _:next(answers),output=output.append,stdin=terminal(False),stdout=terminal(False),environ={'TERM':'xterm'})
    assert screen.results('Finished',['Short summary'],'Technical-only sentinel')=='back'
    assert any('Technical-only sentinel' in line for line in output)
    assert '\x1b' not in '\n'.join(output)
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();f.info['version']=[3,15,0]
        prompts=display(f,['1','1'])
        f.manager.run_screen('Update packages',lambda:f.manager.guided_maintenance('sync'))
        assert any('Recommended action: Rebuild Python environment' in line for line in f.output)
        assert sum(p=='Choose [2]: ' for p in prompts)==1
        assert list(f.root.glob('.venv.backup-*'))
        assert any('Previous environment saved as backup:' in line for line in f.output)
    with TemporaryDirectory() as directory:
        f=prepared(directory);f.output.clear();prompts=display(f,['3','1','3','1','1'])
        before=sum('install' in args for args,_ in f.calls)
        def select_new():
            assert sum('install' in args for args,_ in f.calls)==before
            assert not list(f.root.glob('.venv.backup-*'))
            f.info['version']=[3,15,0]
        with patch.object(f.manager,'choose_python',side_effect=select_new),patch.object(f.manager,'choose_packages') as source:
            f.manager.run_screen('Repair environment',lambda:f.manager.guided_maintenance('repair'))
        assert sum(p=='Choose [2]: ' for p in prompts)==2 # one custom-settings choice, one actual approval
        assert list(f.root.glob('.venv.backup-*'))
        source.assert_not_called()
    with TemporaryDirectory() as directory:
        f=prepared(directory);original=f.manager.runner;f.output.clear()
        def interrupted(args,**kwargs):
            if '-m' in args and args[args.index('-m')+1]=='pip' and 'install' in args:raise KeyboardInterrupt()
            return original(args,**kwargs)
        f.manager.runner=interrupted
        sequence=iter(['1'])
        def eof_after_confirmation(prompt):
            try:return next(sequence)
            except StopIteration:raise EOFError()
        f.manager.ask=eof_after_confirmation
        assert f.manager.run_screen('Update packages',lambda:f.manager.guided_maintenance('sync'))=='exit'
        assert any('Operation interrupted' in line for line in f.output)
        assert any('not been rolled back' in line for line in f.output)
        assert any('Results left on screen' in line for line in f.output)


def pty_menu(environ):
    master,slave=pty.openpty()
    process=subprocess.Popen([sys.executable,'-B','-I','-S',str(ROOT/'lvs_environment_manager.py')],
        stdin=slave,stdout=slave,stderr=slave,env={**os.environ,**environ})
    os.close(slave);data=bytearray();deadline=time.monotonic()+10
    try:
        os.write(master,b'8\n')
        while time.monotonic()<deadline:
            ready,_,_=select.select([master],[],[],.1)
            if ready:
                try:chunk=os.read(master,65536)
                except OSError as error:
                    if error.errno==errno.EIO:break
                    raise
                if not chunk:break
                data.extend(chunk)
            elif process.poll() is not None:break
        else:raise AssertionError('PTY menu failed to exit')
        assert process.wait(timeout=2)==0,bytes(data)
    finally:
        if process.poll() is None:process.kill();process.wait()
        os.close(master)
    return bytes(data)


def run_environment_ui_real_terminal_checks():
    # These actual menu exits never inspect or maintain the development venv.
    with patch.dict(os.environ,{},clear=False):
        os.environ.pop('NO_COLOR',None)
        assert b'\x1b[2J' in pty_menu({'TERM':'xterm'})
    for environ in [{'TERM':'dumb'},{'TERM':'xterm','NO_COLOR':''}]:
        assert b'\x1b' not in pty_menu(environ)
    result=subprocess.run([sys.executable,'-B','-I','-S',str(ROOT/'lvs_environment_manager.py')],input='8\n',text=True,capture_output=True,env={**os.environ,'TERM':'xterm'},check=True)
    assert '\x1b' not in result.stdout and 'Check environment health' in result.stdout

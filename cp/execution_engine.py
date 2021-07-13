import ast
import asyncio
from execution_context import Node
from datetime import datetime

class ExecutionEngine():
    def __init__(self, whendos,  execution_contexts):
        self.signals = [] # varname, related_whendos from the same instance
        self.timers = {
            'seconds':[],
            'minutes':[],
            'hours':[],
            'days':[]
        } # whendo
        self.universal_whendos = whendos
        self.execution_contexts = execution_contexts
        self.pending_signals = asyncio.Queue()

    def extract_signals(self, comp):
        signals = []
        if isinstance(comp, ast.BoolOp):
            for val in comp.values:
                signals+= self.extract_signals(val)
            return signals
        if isinstance(comp, ast.Compare):
            signals+=self.extract_signals(comp.left)
            for op in comp.comparators:
                signals+=self.extract_signals(op)
        if isinstance(comp, ast.Name):
            signals.append(comp.id)
        if isinstance(comp, ast.BinOp):
            signals+=self.extract_signals(comp.left)
            signals += self.extract_signals(comp.right)
        if isinstance(comp, ast.Call):
            if comp.func.id in ['seconds', 'minutes', 'hours', 'days']:
                signals.append(comp.func.id)
            for arg in comp.args:
                signals+=self.extract_signals(arg)
        if isinstance(comp,  ast.Subscript) and isinstance(comp.slice.value, ast.Str):
            signals.append(comp.value.id+'.'+comp.slice.value.s)
        if isinstance(comp, ast.Attribute):
            if isinstance(comp.value, ast.Attribute):
                signals.append(comp.value.value.id + '.' + comp.value.attr + '.' + comp.attr)
            else:
                signals.append(comp.value.id+'.'+comp.attr)
        return signals

    def add(self, whendo):
        signals = []
        if isinstance(whendo.when, list):
            for comp in whendo.when:
                signals = signals + self.extract_signals(comp)
        else:
            signals = self.extract_signals(whendo.when)
        for signal  in signals:
            if signal in ['seconds', 'minutes', 'hours', 'days']:
                if whendo not in self.timers[signal]: self.timers[signal].append(whendo)
            elif signal.startswith('time.') and signal.split('.')[1] in ['second', 'minute', 'hour']:
                if whendo not in self.timers[signal.split('.')[1]+'s']: self.timers[signal.split('.')[1]+'s'].append(whendo)
            elif signal != 'time' and not  signal.startswith('time.'):
                dsignals = [s for s in self.signals if s['varname']==signal and whendo.instance == s['instance'] and whendo.app ==s['app']]
                if len(dsignals)!=0 and dsignals[0]['whendos'][0].instance == whendo.instance and dsignals[0]['whendos'][0].app == whendo.app:
                    if whendo not in dsignals[0]['whendos']: dsignals[0]['whendos'].append(whendo)
                else:
                    self.signals.append({'varname': signal, 'whendos': [whendo], 'instance': whendo.instance, 'app': whendo.app})
                    if signal in self.execution_contexts[whendo.instance].variables[whendo.app]: # detect signals changed from other modules
                        self.signals.append({'varname': whendo.app + '.' +signal, 'whendos': [whendo], 'instance': whendo.instance, 'app': whendo.app})

                # node based signals
                var = signal.split('.')[0]
                if  var!='me' and isinstance(self.execution_contexts[whendo.instance].get_val(var, {'app': whendo.app, 'variables':{}}), Node): # todo MUMT
                    node = self.execution_contexts[whendo.instance].get_val(var, {'app': whendo.app, 'variables':{}})
                    asignal = node.name+'.'+signal.split('.')[1]
                    dsignals = [s for s in self.signals if s['varname'] == asignal and whendo.instance == s['instance'] and whendo.app ==s['app']]
                    if len(dsignals) != 0 and dsignals[0]['whendos'][0].instance == whendo.instance and dsignals[0]['whendos'][0].app == whendo.app:
                        if whendo not in dsignals[0]['whendos']: dsignals[0]['whendos'].append(whendo)
                    else:
                        self.signals.append({'varname': asignal, 'whendos': [whendo], 'instance': whendo.instance, 'app': whendo.app})


    async def execute(self, whendo, vars = {}):
        if await self.test(whendo, vars):
            await self.do(whendo, vars)
        await asyncio.sleep(0)

    async def test(self, whendo,  vars = {}):
        bc = {'app': whendo.app, 'variables': vars}
        try:
            return (isinstance(whendo.when, list) and await self.execution_contexts[whendo.instance].eval_(
                whendo.when[0], bc) and await self.execution_contexts[whendo.instance].eval_(whendo.when[1], bc)) or (
                not isinstance(whendo.when, list) and await self.execution_contexts[whendo.instance].eval_(whendo.when, bc))
        except Exception as ex:
            raise Exception(ex)

    async def do(self, whendo, vars = {}):
        try:
            await self.execution_contexts[whendo.instance].execute(whendo.do, {'app': whendo.app, 'variables': vars})
            await asyncio.sleep(0)
        except Exception as ex:
            whendo.add_error('Error while executing signals: {}'.format(str(ex)))

    async def process_seconds(self):
        while True:
            await asyncio.sleep(0.5)
            for secondwhendo in self.timers['seconds']:
                await asyncio.sleep(0)
                await self.execute(secondwhendo)


    async def process_minutes(self):
        while True:
            sleeptime = 60 - datetime.utcnow().second
            await asyncio.sleep(sleeptime)
            for minutewhendo in self.timers['minutes']:
                await asyncio.sleep(0)
                await self.execute(minutewhendo)

    async def process_hours(self):
        while True:
            sleeptime = 60.0 - (datetime.utcnow().minute+datetime.utcnow().second/60)
            await asyncio.sleep(sleeptime*60)
            for hourwhendo in self.timers['hours']:
                await asyncio.sleep(0)
                await self.execute(hourwhendo)

    async def process_days(self):
        while True:
            sleeptime = (24 - datetime.utcnow().hour)*60+60.0 - (datetime.utcnow().minute+datetime.utcnow().second/60)
            await asyncio.sleep(sleeptime*60)
            for daywhendo in self.timers['days']:
                await asyncio.sleep(0)
                await self.execute(daywhendo)

    async def process_signals(self):
        while True:
            try:
                signal = await self.pending_signals.get()
                instance = None
                user = None
                sender = None
                vars = {}
                if isinstance(signal, tuple):
                    signal, user, val, instance, session = signal
                    vars['signal'] = signal
                    vars['me']  =  Node(self.execution_contexts[instance].messages, user, instance)
                    parts = signal.split('.')
                    if len(parts) == 2:
                        vars['me'].set(parts[1], val)
                    else:
                        vars['me'].set(parts[1], {parts[2]:val})
                    vars['me'].session = session
                elif isinstance(signal,list): # signal, instance, sender(, session)
                    instance = signal[1]
                    if len(signal)>=3:
                        if ':' in signal[2]:
                            ss = signal[2].split(':')
                            inst, sender = ss[0], ss[1]
                        else:
                            sender = signal[2]
                            inst = instance
                        vars['sender'] = Node(self.execution_contexts[instance].messages, sender, inst)
                        if len(signal) >= 4:
                            vars['sender'].session = signal[3]
                        signal = signal[0]
                        vars['signal'] = signal
                    else:
                        signal = signal[0]
                        vars['signal'] = signal
                dsignal = [s for s in self.signals if s['varname'] == signal and s['instance']==instance]
                if len(dsignal) != 0:
                    coros = []
                    for ds in dsignal:
                        cont = None
                        val = None
                        for whendo in ds['whendos']:
                            if isinstance(whendo.do[0], ast.Continue):
                                cont = whendo.when.left.id
                                val = whendo.when.comparators[0].id
                            elif cont:
                                if isinstance(whendo.when, list):
                                    cmp = whendo.when[0]
                                else:
                                    cmp = whendo.when
                                if isinstance(cmp, ast.Compare) and cmp.left.id == cont \
                                        and cmp.comparators[0].id == val:
                                    continue
                            if await self.test(whendo, vars):
                                coros.append(self.do(whendo, vars))
                    await asyncio.gather(*coros)
                self.pending_signals.task_done()
            except Exception as ex:
                pass

    def start(self):
        asyncio.Task(self.process_days())
        asyncio.Task(self.process_hours())

        asyncio.Task(self.process_minutes())
        asyncio.Task(self.process_seconds())
        asyncio.Task(self.process_signals())

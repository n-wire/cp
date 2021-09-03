import ast
import operator as op
import json
import time
from datetime import datetime, timedelta
from calendar import timegm
import copy
from types import coroutine
import motor.motor_asyncio
from bson.objectid import ObjectId
import asyncio
import random
import requests
import string
import inspect

try:
    import cp.myemail as myemail
except:
    myemail = None

from config import nw_server

mongo = motor.motor_asyncio.AsyncIOMotorClient(nw_server, 27017)

class ExecutionContext():
    def __init__(self, instance, whendo, exec_loop, messages):
        self.universal_whendos = whendo
        self.exec_loop = exec_loop
        self.instance = instance
        self.messages = messages
        self.nodes = []
        self.pvs = []
        self.theapp = {}  # {user@mail: appid}
        self.themodule = 'module'
        self.apps = []
        self.owners = {} # appid: email
        self.variables = {'nodes': [], 'apps': self.apps}
        self.nodewaiters = []
        '''
            briefcase : {app, variables}
        '''
        self.operators = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Mod: op.mod,
                          ast.Div: op.truediv, ast.Pow: op.pow, ast.BitXor: op.xor,
                          ast.And: op.and_, ast.Or: op.or_, ast.Not: op.not_,
                          ast.Is: op.is_, ast.IsNot: op.is_not, ast.NotIn: self.containsnot,
                          ast.Gt: op.gt, ast.GtE: op.ge, ast.Eq: op.eq, ast.Lt: op.lt, ast.LtE: op.le,
                          ast.Lambda: None, # ast.Await: None, ast.Yield: None,
                          ast.USub: op.neg, ast.NotEq: op.ne, ast.In: self.contains}

    def contains(self,a,b):
        return a in b

    def containsnot(self,a,b):
        return a not in b

    def reset(self, theapp, owner):
        self.variables[theapp] =  {'outputs': [], 'inputs': []}
        self.owners[theapp] = owner

        whendos = [wd for wd in self.universal_whendos if wd.instance==self.instance and wd.app==theapp]
        for whendo in whendos:
            self.universal_whendos.remove(whendo)

        for whendo in [wd for wd in self.exec_loop.timers['seconds'] if wd.instance==self.instance and wd.app==theapp]:
            self.exec_loop.timers['seconds'].remove(whendo)

        for whendo in [wd for wd in self.exec_loop.timers['minutes'] if wd.instance==self.instance and wd.app==theapp]:
            self.exec_loop.timers['minutes'].remove(whendo)

        for whendo in [wd for wd in self.exec_loop.timers['hours'] if wd.instance==self.instance and wd.app==theapp]:
            self.exec_loop.timers['hours'].remove(whendo)

        for whendo in [wd for wd in self.exec_loop.timers['days'] if wd.instance==self.instance and wd.app==theapp]:
            self.exec_loop.timers['days'].remove(whendo)
        for signal in [s for s in self.exec_loop.signals if s['whendos'][0].instance==self.instance and s['whendos'][0].app==theapp]:
            self.exec_loop.signals.remove(signal)


    async def engine_process(self, scriptlines, user): # todo interactive shell, what to do with local vars?
        if user not in self.theapp:
            self.theapp[user] = "shell"
            self.reset(self.theapp[user], user)
        bc = self.variables[self.theapp[user]] if self.theapp[user] in self.variables else {}
        script = self.pre_process(scriptlines, user)
        return await self.evaluate(script, {'app': self.theapp[user], 'module': 'shell', 'variables': bc})

    def pre_process(self, scriptlines,  user):
        sequence = None
        lines = []
        seq_num = 0
        sequence_prefix = None
        for line in scriptlines:
            if line.startswith('sequencer'):  # todo MUMT  --> done
                sequence = line[line.index(' ') + 1: line.index(':')]
                seq_num = 0
                line = line.replace('sequencer ', 'def sequencer_').replace(':', '():')
            if ' ' in line and line.strip() != '' and line.strip() not in ['else:', 'try:', 'except:'] and line.split()[0][-1] == ':' and sequence != None:  # todo handle when there is space between statename and colon
                self.variables[self.theapp[user]][line.split()[0][:-1]] = seq_num
                seq_num = seq_num + 1
                if sequence_prefix == None:
                    sequence_prefix = line[:line.index(line.strip())]
                line = line.replace(line.split()[0], 'if ' + sequence + '==' + line.split()[0])
            if line.strip().startswith('when '):
                line = line.replace('when', 'while')
            if line.strip().startswith('always ') or line.strip().startswith('always:'):
                line = line.replace('always', 'while True')
            if ' goto ' in line:
                line = line.replace('goto', sequence + '=')
            if sequence_prefix != None and not line.startswith(sequence_prefix):
                sequence = None
                sequence_prefix = None
            lines.append(line)
        return '\n'.join(lines)

    def compile_file(self, scriptlines):
        program = ast.parse(self.pre_process(scriptlines), filename=self.themodule).body
        results = []
        for p in program:
            results.append(ast.dump(p))
        return '\n'.join(results)

    async def engine_process_file(self, scriptlines,  user):
        script = self.pre_process(scriptlines, user)
        # no local  variables at this point. only global application level variables
        await self.evaluate(script, {'app': self.theapp[user], 'module': self.themodule, 'variables': self.variables[self.theapp[user]]})
        
    def add_node(self, node, gateway):
        self.pvs.append(node)
        self.variables['nodes'].append(Node(self.messages, node, gateway))
        self.exec_loop.pending_signals.put_nowait(['nodes', gateway])
        
    def anounce(self, node, gateway):
        waiters = [waiter for waiter in self.nodewaiters if waiter['nodename']==node]
        for waiter in waiters:
            self.messages.put_nowait(('{} node {} {} {} cp'.format(waiter['waiter'], self.variables['nodes'][-1].json(), node, gateway), None))

    def set_val(self, var, val, briefcase):
        if var in briefcase['variables']:
            briefcase['variables'][var] = val
        elif var in self.variables[briefcase['app']]:
            self.variables[briefcase['app']][var] = val
        elif var in self.variables:
            self.variables[var] = val
        else:
            briefcase['variables'][var] = val

    def is_defined(self, var, briefcase):
        if briefcase['app'] == None: raise Exception('Application Context not set!')
        if var in self.variables[briefcase['app']]:
            return True
        elif var in briefcase['variables']:
            return True
        elif var in self.variables:
            return True
        else:
            return False

    def get_val(self, var, briefcase):
        if var in briefcase['variables']:
            return briefcase['variables'][var]
        elif var in self.variables[briefcase['app']]:
            return self.variables[briefcase['app']][var]
        elif var in self.variables:
            return self.variables[var]
        else:
            raise Exception('undefined: ' + var)

    async def assign(self, expr, val, briefcase, more=[]):
        if isinstance(expr, ast.Name):
            if expr.id == 'db':
                val = await self.eval_(val, briefcase)
                if isinstance(val, tuple):
                    if len(val) == 3:
                        lst = json.dumps(val[1])
                        opt = json.dumps(val[2])
                        self.messages.put_nowait(('{}:{} set {} {} {} {} ee'.format(self.instance, 'db', more[0].value.id,val[0], lst, opt),None))
                    elif len(val) ==2:
                        lst = json.dumps(val[1])
                        self.messages.put_nowait(('{}:{} set {} {} {} ee'.format(self.instance, 'db', more[0].value.id,val[0], lst), None))
                    else:
                        self.messages.put_nowait( ('{}:{} set {} {} ee'.format(self.instance, 'db', more[0].value.id, val[0]), None))
                else:
                    if isinstance(val, list):
                        for v1 in val:
                            v1 = {v: v1[v] for v in v1 if type(v1[v]) != func}
                        val = json.dumps(val)
                    elif isinstance(val, dict):
                        val = json.dumps({v:val[v] for v in val if type(val[v])!=func})
                    if isinstance(more[0], ast.Name):
                        self.messages.put_nowait(('{}:{} set {} {} ee'.format(self.instance, 'db', more[0].id,str(val)), None))
                    elif isinstance(more[0].value, ast.Call):
                        fid = more[0].value.func.id
                        args = []
                        for arg in more[0].value.args:
                            args.append(await self.eval_(arg, briefcase))
                        if len(args)==1:
                            self.messages.put_nowait(('{}:{} set {} {} {} ee'.format(self.instance, 'db',fid, json.dumps(args[0]),str(val)), None))
                        elif len(args)==2: # used for index creation
                            self.messages.put_nowait(('{}:{} set {} {} {} {} ee'.format(self.instance, 'db', fid, json.dumps(args[0]), json.dumps(args[1]), str(val)), None))
            else:
                val = await self.eval_(val, briefcase)
                var = expr.id
                if more != []:
                    target = self.get_val(var, briefcase) # todo MUMT --> done
                    for m in reversed(more[1:]):
                        target = target[await self.eval_(m, briefcase)]
                    m = more[0]
                    index = await self.eval_(m, briefcase)
                    target[index] = val
                    if var in self.apps and index in self.variables[var]['outputs']:
                        self.messages.put_nowait(('{}:ee val {} {} {}'.format(self.instance, index, str(json.dumps(val)), var), None))
                    if var == briefcase['app']:
                        self.exec_loop.pending_signals.put_nowait([index, self.instance])
                    else:
                        self.exec_loop.pending_signals.put_nowait([var + '.' + str(index),  self.instance])
                elif not self.is_defined(var,briefcase) or self.get_val(var, briefcase) != val:
                    self.set_val(var, val, briefcase)
                    self.exec_loop.pending_signals.put_nowait([var, self.instance])
                if var in self.variables[briefcase['app']]['outputs']:
                    val = self.get_val(var, briefcase)
                    self.messages.put_nowait(('{}:ee val {} {} {}'.format(self.instance, var, str(json.dumps(val)),  briefcase['app']), None))
        elif isinstance(expr, ast.Subscript):
            index = expr.slice
            more.append(index)
            await self.assign(expr.value, val, briefcase, more)
        elif isinstance(expr, ast.Attribute):
            more.append(expr.attr)
            await self.assign(expr.value, val, briefcase, more)
        elif isinstance(expr, Node):
            expr[more[0]] = await self.eval_(val, briefcase)
        else:
            await self.assign(await self.eval_(expr, briefcase), val, briefcase, more)

    async def evaluate(self, exp, briefcase):
        program = ast.parse(exp, filename=self.themodule).body
        results = []
        for expression in program:
            if isinstance(expression, ast.Assign):
               if isinstance(expression.targets[0], ast.Tuple):
                    for i in range(len(expression.targets[0].elts)):
                        await self.assign(expression.targets[0].elts[i], expression.value.elts[i], briefcase, [])
               else:
                    await self.assign(expression.targets[0], expression.value, briefcase, [])
            elif isinstance(expression, ast.AugAssign):
                val = self.operators[type(expression.op)](await self.eval_(expression.target, briefcase), await self.eval_(expression.value, briefcase))
                await self.assign(expression.target, val, briefcase, [])
            elif isinstance(expression, ast.While) or isinstance(expression, ast.FunctionDef) or isinstance(expression, ast.Delete):
                await self.eval_(expression,briefcase)
                # elif isinstance(expression, ast.AugAssign):
                #   if isinstance(expression.op, ast.Add):
                #        await self.assign(expression.target, await self.eval_(expression.target, briefcase)+ await self.eval_(expression.value, briefcase), briefcase, [])
            elif isinstance(expression, ast.ClassDef):
                self.variables[briefcase['app']][expression.name] = _class(expression.body)
            else:  # ast.Expr or
                result = await self.eval_(expression.value, briefcase)
                results.append(result)
        return ', '.join(str(r) for r in results)

    async def execute(self, program, briefcase):
        result = None
        for expression in program:
            if not result is None: return result
            try:
                if isinstance(expression, ast.Assign):
                   if isinstance(expression.targets[0], ast.Tuple):
                        for i in range(len(expression.targets[0].elts)):
                            await self.assign(expression.targets[0].elts[i], expression.value.elts[i], briefcase, [])
                   else:
                        await self.assign(expression.targets[0], expression.value,briefcase,[])
                elif isinstance(expression, ast.Return):
                    return await self.eval_(expression.value, briefcase)
                elif isinstance(expression, ast.If):
                    if await self.eval_(expression.test, briefcase):
                        result = await self.execute(expression.body, briefcase)
                    elif len(expression.orelse) !=0:
                        result = await self.execute(expression.orelse, briefcase)
                elif isinstance(expression, ast.Try):
                    try:
                        result = await self.execute(expression.body, briefcase)
                    except Exception as ex:
                        if expression.handlers[0].name:
                            briefcase['variables'][expression.handlers[0].name] = str(ex)
                        result = await self.execute(expression.handlers[0].body, briefcase)
                    finally:
                        if expression.finalbody != []:
                            result = await self.execute(expression.finalbody, briefcase)
                elif isinstance(expression, ast.For):
                    for e in await self.eval_(expression.iter, briefcase):
                        briefcase['variables'][expression.target.id] = e
                        result = await self.execute(expression.body, briefcase)
                else:
                    r = await self.eval_(expression, briefcase)
                    if len(program) == 1:
                        return r  # to take care of lamdas
            except Exception as ex:
                raise Exception('{}: at line {} col {}'.format(str(ex), expression.lineno, expression.col_offset))
        return result

    async def reduce(self, seq, fnc, briefcase):
        tally = seq[0]
        for next in seq[1:]:
            tally = await self.eval_func(fnc, [tally, next], briefcase)
        return tally

    async def sort(self, seq, fnc, briefcase):
        list_annotated = [(await self.eval_func(fnc, [item], briefcase), item) for item in seq]
        list_annotated.sort()
        return [x for key, x in list_annotated]

    def sendPorts(self, sender, briefcase):
        ports = [p for p in self.variables[briefcase['app']]['inputs']] # todo MUMT --> done
        for p in self.variables[briefcase['app']]['outputs']:
            if p not in ports: ports.append(p)
        self.messages.put_nowait(('{}:{} ports {} {}'.format(self.instance, sender, ' '.join(p for p in ports),  [briefcase['app']]), None))

    async def eval_func(self, fun, paras, briefcase):
        mybriefcase = {'app': briefcase['app'], 'variables':{}}
        try:

            paras += [await self.eval_(d, briefcase) for d in fun.params.defaults[-(len(fun.params.args) - len(paras)):]]
            for p in range(len(fun.params.args)):  # todo MUMT --> done
                self.set_val(fun.params.args[p].arg, paras[p], mybriefcase)
            if fun.params.vararg:
                self.set_val(fun.params.vararg.arg, paras[len(fun.params.args): (-1 if fun.params.kwarg else None)], mybriefcase)
            if fun.params.kwarg:
                if len(paras)>len(fun.params.args):
                    self.set_val(fun.params.kwarg.arg, paras[-1], mybriefcase)
                else:
                    self.set_val(fun.params.kwarg.arg, None, mybriefcase)
        except Exception as ex:
            pass
        result = await self.execute(fun.body if isinstance(fun.body, list) else [fun.body], mybriefcase)
        return result

    async def eval_class(self, clss, paras, briefcase):
        ss = {}
        for expr in clss.body:
            if isinstance(expr, ast.Assign):
                ss[expr.targets[0].id] = await self.eval_(expr.value, briefcase)
            elif isinstance(expr, ast.FunctionDef):
                ss[expr.name] = func(expr.body, expr.args)
        if '__init__' in ss:
            await self.eval_func(ss['__init__'], [ss]+paras, briefcase)
        elif paras and type(paras[0]) == dict:
            for f in paras[0]:
                ss[f] = paras[0][f]
        return ss

    async def eval_(self, node, briefcase):
        if isinstance(node, ast.Num):  # <number>
            return node.n
        elif isinstance(node, ast.Str):  # string
            return node.s
        elif isinstance(node, ast.BinOp):  # <left> <operator> <right>
            return self.operators[type(node.op)](await self.eval_(node.left, briefcase), await self.eval_(node.right, briefcase))
        elif isinstance(node, ast.UnaryOp):  # <operator> <operand> e.g., -1
            return self.operators[type(node.op)](await self.eval_(node.operand, briefcase))
        elif isinstance(node, ast.Name):
            if self.is_defined(node.id, briefcase): # todo MUMT --> done
                return self.get_val(node.id, briefcase)
            elif node.id == 'time':
                return time.time()
            elif node.id == 'db':
                db = mongo[self.instance]
                return  await db.list_collection_names()
            else:
                raise NameError('undefined variable: ' + node.id)
        elif isinstance(node, ast.List):
            thelist = []
            for item in node.elts:
                thelist.append(await self.eval_(item, briefcase))
            return thelist
        elif isinstance(node, ast.In):
            pass
        elif isinstance(node, ast.Dict):
            thedict = {}
            for k in range(0, len(node.keys)):
                if isinstance(node.keys[k], ast.Name):
                    thedict[node.keys[k].id] = await self.eval_(node.values[k], briefcase)
                else:
                    thedict[await self.eval_(node.keys[k], briefcase)] = await self.eval_(node.values[k], briefcase)
            return thedict
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id=='time':
                exp = None
                if node.attr == 'hour':
                    exp = time.localtime(time.time()).tm_hour
                elif node.attr == 'minute':
                    exp = time.localtime(time.time()).tm_min
                elif node.attr == 'second':
                    exp = time.localtime(time.time()).tm_sec
                elif node.attr == 'year':
                    exp = time.localtime(time.time()).tm_year
                elif node.attr == 'month':
                    exp = time.localtime(time.time()).tm_mon
                elif node.attr == 'mday':
                    exp = time.localtime(time.time()).tm_mday
                elif node.attr == 'wday':
                    exp = time.localtime(time.time()).tm_wday
                elif node.attr == 'yday':
                    exp = time.localtime(time.time()).tm_yday
                return exp
            thevar = await self.eval_(node.value, briefcase)
            theindex = await self.eval_(node.attr,  briefcase)
            if theindex in thevar or isinstance(thevar,  Node):
                return thevar[theindex]
            elif isinstance(thevar, str):
                try:
                    return {
                        'split': thevar.split,
                        'index': thevar.index,
                        'endswith': thevar.endswith,
                        'startswith': thevar.startswith,
                        'find': thevar.find,
                        'join': thevar.join,
                        'replace': thevar.replace,
                        'lower': thevar.lower,
                        'upper': thevar.upper,
                        'strip': thevar.strip
                    }[theindex]
                except:
                    raise Exception(theindex + ' is not a member of str')
            elif isinstance(thevar, list):
                try:
                    return {
                        'append': thevar.append,
                        'clear': thevar.clear,
                        'copy': thevar.copy,
                        'count': thevar.count,
                        'extend': thevar.extend,
                        'index': thevar.index,
                        'inser': thevar.insert,
                        'pop': thevar.pop,
                        'remove': thevar.remove,
                        'reverse': thevar.reverse,
                        'sort': thevar.sort
                    }[theindex]
                except:
                    raise Exception(theindex + ' is not a member of list')
            elif isinstance(node.value, ast.Name):
                raise Exception(theindex + ' is not a member of ' + node.value.id)
            else:
                pass
        elif isinstance(node, ast.Call):
            thelist = []
            for item in node.args:
                thelist.append(await self.eval_(item, briefcase))
            if node.keywords:
                kwargs = {}
                for item in node.keywords:
                    kwargs[item.arg] = await  self.eval_(item.value, briefcase)
                thelist.append(kwargs)
            if  isinstance(node.func, ast.Subscript):
                return (None,thelist)
            elif isinstance(node.func, ast.Attribute):
                try:
                    fun = await self.eval_(node.func,briefcase) #self.
                    if not isinstance(fun, func):
                        result = fun(*thelist)
                        if inspect.iscoroutine(result):
                            result = await result
                    elif fun.params.args != [] and fun.params.args[0].arg == 'self':
                        thelist = [self.get_val(node.func.value.id, briefcase)]+thelist
                        result = await self.eval_func(fun, thelist, briefcase)
                    else:
                        bc = {'app': node.func.value.id, 'module': briefcase['module'], 'variables': self.variables[node.func.value.id]}
                        result = await self.eval_func(fun, thelist, bc)
                    return result
                except KeyError as ex:
                    raise Exception("object has no function:" +  str(ex))
            else:
                if node.func.id == 'str':
                    if len(thelist) == 1:
                        return str(thelist[0])
                    else:
                        return thelist[0].format(*thelist[1:])
                elif node.func.id == 'ftime':  # https://docs.python.org/2/library/time.html
                    date = datetime(1970, 1, 1) + timedelta(seconds=thelist[1])
                    return date.strftime(thelist[0])  # thelist[0] time ticks, thelist[1] format %x for date %X for time
                elif node.func.id == 'date':
                    tm = thelist[0]
                    fmt = thelist[1] if len(thelist)>1 else '%Y-%m-%d'
                    return timegm(datetime.strptime(tm, fmt).utctimetuple())
                elif node.func.id =='abs':
                    return abs(thelist[0])
                elif node.func.id == 'len':
                    return len(thelist[0])
                elif node.func.id == 'reduce':
                    return await self.reduce(thelist[0], thelist[1], briefcase)
                elif node.func.id == 'sort':
                    return await self.sort(thelist[0], thelist[1], briefcase)
                elif node.func.id == 'node':
                    nodes = [n for n in self.variables['nodes'] if n['name'] == thelist[0]] # todo MUMT
                    if len(nodes) != 0:
                        return nodes[0]
                    else:
                        thenode = Node(self.messages, thelist[0], thelist[1] if len(thelist) > 1 else self.instance)
                        return thenode
                elif node.func.id == 'int':
                    if len(thelist) > 1:
                        return int(thelist[0], thelist[1])
                    return int(thelist[0])
                elif node.func.id == 'float':
                    return float(thelist[0])
                elif node.func.id == 'type':
                    return str(type(thelist[0]))[8:-2]
                elif node.func.id == 'copy':
                    return copy.copy(thelist[0])
                elif node.func.id == 'deepcopy':
                    return copy.deepcopy(thelist[0])
                elif node.func.id == 'randint':
                    return random.randint(thelist[0], thelist[1])
                elif node.func.id == 'range':
                    if len(thelist) == 1:
                        return range(thelist[0])
                    elif len(thelist) == 2:
                        return range(thelist[0], thelist[1])
                    else:
                        return range(thelist[0], thelist[1], thelist[2])
                elif node.func.id == 'app':
                    if len(self.apps) < 6:
                        email = self.owners[ briefcase["app"]]
                        self.theapp[email] = thelist[0]
                        self.reset(self.theapp[email], email)
                        if self.theapp[email] not in self.apps:
                            self.apps.append(self.theapp[email])
                        return ''
                    else:
                        raise Exception('You can only run 6 apps!')
                elif node.func.id == 'switch_to':
                    if thelist[0] in self.apps:
                        email = self.owners[briefcase["app"]]
                        self.theapp[email] = thelist[0]
                        # self.messages.put_nowait((f'cp subscribe {thelist[0]} val {email}', None))
                    return ''
                elif node.func.id == 'owner':
                    return self.owners[thelist[0]] if thelist[0] in self.owners else None
                elif node.func.id == 'endapp':
                    self.themodule = 'module'
                    # self.theapp = 'app'
                    return ''
                elif node.func.id == 'module':
                    self.themodule = thelist[0]
                    return ''
                elif node.func.id == 'print':
                    current_user = self.owners[briefcase["app"]]
                    self.messages.put_nowait(('{} val script {} {}:ee'.format(current_user, json.dumps(thelist), self.instance), None))
                    return ''
                elif node.func.id == 'kill':
                    email = [k for k in self.theapp if self.theapp[k] == briefcase["app"]][0]
                    if thelist[0] == self.theapp[email]:
                        del self.theapp[email]
                        self.themodule = 'module'
                    if thelist[0] in self.apps:
                        self.reset(thelist[0], email)
                        del self.variables[thelist[0]]
                        del self.owners[thelist[0]]
                        self.apps.remove(thelist[0])
                    return ''
                elif node.func.id == 'get_layout':
                    db = mongo['nodewire']
                    apps = db['apps']
                    app = await apps.find_one({'title':thelist[0]})
                    if app != None:
                        #for layout in app['layout']:
                        #    layout['content'] = layout['content'].replace('\n',' ').replace('"',"'")
                        self.messages.put_nowait((f"window set xml `{app['layout'][0]['content']}` {self.instance}:ee", None))
                        return app['layout']
                    else:
                        return None
                elif node.func.id == 'exec':
                    if len(self.apps) >= 5: raise Exception('You can only run 5 apps!')
                    db = mongo['nodewire']
                    email = [k for k in self.theapp if self.theapp[k] == briefcase["app"]][0]
                    user = await db.users.find_one({'email': email})
                    if user  == None: return 'error current user cant run scripts'
                    apps = user['apps']
                    for app_id in apps:
                        app = await db.apps.find_one({'title':  app_id})
                        if app!=None and app['title'] == thelist[0]:
                            tmp = self.theapp[email]
                            self.theapp[email] = app['title']
                            self.reset(app['title'], email)
                            if app['title'] not in self.apps: self.apps.append(app['title'])
                            for script in app['script']:
                                self.themodule = script['name']
                                lines = script['content'].splitlines()
                                await self.engine_process_file(lines, email)
                            for sketch in app['sketch']:
                                pass
                            self.theapp[email] = tmp
                            return ''

                    app = await db.store.find_one({'app_name': thelist[0]})
                    if app != None:
                        self.theapp[email] = app['app_name']
                        self.reset(self.theapp[email], email)
                        if self.theapp[email] not in self.apps: self.apps.append(self.theapp[email])
                        appcontent = await db.apps.find_one({'_id': app['app_id']})
                        for script in appcontent['script']:
                            lines = script['content'].splitlines()
                            await self.engine_process_file(lines, email)
                        for sketch in appcontent['sketch']:
                            pass
                        return ''
                elif node.func.id == 'accountInfo':
                    db = mongo['nodewire']
                    # users = db['users']
                    user = await db.users.find_one({'email': thelist[0]}, {'fullname':1, 'trust_zones': 1})
                    if user is not None:
                        return {
                            'fullname': user['fullname'],
                            'authorized': self.instance in user['trust_zones']
                        }
                    return None
                elif node.func.id == 'whois':
                    db = mongo['nodewire']
                    gw = await db.instances.find_one({'instance_id': thelist[0]})
                    return gw["users"][0]['user_instance_and_node_name'].split(':')[1]
                elif node.func.id == 'get':
                    if briefcase['app']!='shell':
                        self.messages.put_nowait((f"{thelist[0]} get {thelist[1]} {self.instance}:{briefcase['app']}", None))
                elif node.func.id in ['seconds', 'minutes', 'days', 'hours']:
                    return {
                        'seconds': thelist[0],
                        'minutes': thelist[0] * 60,
                        'hours': thelist[0] * 3600,
                        'days': thelist[0] * 3600 * 24
                    }[node.func.id]
                elif node.func.id in self.variables[briefcase['app']]:
                    fun = self.variables[briefcase['app']][node.func.id]
                    if isinstance(fun, func):
                        result = await self.eval_func(fun, thelist, briefcase)
                    elif isinstance(fun, _class):
                        result = await self.eval_class(fun, thelist, briefcase)
                    elif callable(fun):
                        result = fun(thelist)
                        if inspect.iscoroutine(result):
                            result = await result
                    if not result is None: return result
                else:
                    raise Exception('undefined function: ' + node.func.id)
                #return (node.func.id, thelist)
        elif isinstance(node, ast.Lambda):
            lam = func(node.body, node.args)
            return lam
        elif isinstance(node, ast.Delete):
            for var in node.targets:
                if isinstance(var, ast.Subscript):
                    del self.get_val(var.value.id, briefcase)[await self.eval_(var.slice, briefcase)]
                elif var.id in self.variables:
                    del self.variables[var.id]
                elif var.id in briefcase['variables']:
                    del briefcase['variables'][var.id]
        elif isinstance(node, ast.Index):
            if isinstance(node.value, ast.Num):
                return node.value.n
            elif isinstance(node.value, ast.Str):
                return  node.value.s
            else:
                return await self.eval_(node.value, briefcase)
        elif isinstance(node, ast.Slice):
            lower = await self.eval_(node.lower, briefcase) if node.lower else None
            step = await self.eval_(node.step, briefcase) if node.step else None
            upper = await self.eval_(node.upper, briefcase) if node.upper else None
            val = slice( lower, upper, step)
            return val
        elif isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == 'db' and isinstance(node.slice,  ast.Call): # and isinstance(node.slice.value, ast.Call):
                if isinstance(node.slice.func, ast.Attribute):
                    fid = node.slice.func.value.id
                    fn = node.slice.func.attr
                else:
                    fid = node.slice.func.id
                    fn = None
                args = []
                for arg in node.slice.args:
                    args.append(await self.eval_(arg, briefcase))
                if fn:
                    if len(args) == 1: args.append(None)
                    if len(args) == 2: args.append({})
                    if fn == 'first':
                        args[2]['$limit'] = 1
                    elif fn == 'last':
                        args[2]['$limit'] = 1
                        args[2]['$sort'] = {'$natural':-1}

                db = mongo[self.instance]
                collection = db[fid]
                if args[0] == 'aggregate' or type(args[0]) is list:
                    pipeline = args[0] if type(args[0]) is list else args[1]
                    results = await collection.aggregate(pipeline).to_list(None)
                    rs = []
                    for result in results:
                        if '_id' in result: result['_id'] = str(result['_id'])
                        rs.append(result)
                        #rs.append(ast.literal_eval(json.dumps(result)))
                    return rs
                else:
                    query = args[0]
                    if '_id' in query and not isinstance(query['_id'], dict): query['_id'] = ObjectId(query['_id'])
                    if len(args) >= 3:
                        sort = args[2]['$sort'] if '$sort' in args[2] else {}
                        limit = args[2]['$limit'] if '$limit' in args[2] else {}
                        skip = args[2]['$skip'] if '$skip' in args[2] else 0
                        if sort!={} and type(sort) == dict:
                            sort = list(sort.items())
                        if sort and limit:
                            results = await collection.find(query, args[1]).skip(skip).sort(sort).limit(limit).to_list(None)
                        elif sort:
                            results = await collection.find(query, args[1]).skip(skip).sort(sort).to_list(None)
                        elif limit:
                            results = await collection.find(query, args[1]).skip(skip).limit(limit).to_list(None)
                        else:
                            results = await collection.find(query, args[1]).skip(skip).to_list(None)
                    elif len(args)>=2:
                        results = await collection.find(query, args[1]).to_list(None)
                    else:
                        if query == 'indices':
                            return await collection.index_information()
                        else:
                            results = await collection.find(query).to_list(None)
                    rs = []
                    for result in results:
                        if '_id' in result: result['_id'] = str(result['_id'])
                        rs.append(result)
                    return (rs[0] if rs else None) if fn else rs
            elif isinstance(node.value, ast.Name) and node.value.id=='time' and isinstance(node.slice.value, ast.Str):
                index = node.slice.value.s
                if index == 'hour':
                    exp = time.localtime(time.time()).tm_hour
                elif index == 'minute':
                    exp = time.localtime(time.time()).tm_min
                elif index == 'second':
                    exp = time.localtime(time.time()).tm_sec
                elif index == 'year':
                    exp = time.localtime(time.time()).tm_year
                elif index == 'month':
                    exp = time.localtime(time.time()).tm_mon
                elif index == 'mday':
                    exp = time.localtime(time.time()).tm_mday
                elif index == 'wday':
                    exp = time.localtime(time.time()).tm_wday
                elif index == 'yday':
                    exp = time.localtime(time.time()).tm_yday
                return exp
            else:
                index = await self.eval_(node.slice, briefcase)
                val = await self.eval_(node.value, briefcase)
                return val[index]
        elif isinstance(node, ast.Compare):
            left = await self.eval_(node.left, briefcase)
            right = await self.eval_(node.comparators[0], briefcase)
            return self.operators[type(node.ops[0])](left, right)
        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for exp in node.values:
                    if not await self.eval_(exp, briefcase): return False
                return True
            elif isinstance(node.op, ast.Or):
                for exp in node.values:
                    if await self.eval_(exp, briefcase): return True
                return False
            else:
                return self.operators[type(node.op)](await self.eval_(node.values[0], briefcase), await self.eval_(node.values[1], briefcase))
        elif isinstance(node, bool):
            return node
        elif isinstance(node, ast.ListComp):
            result = []
            for g in node.generators:
                if isinstance(g, ast.comprehension):
                    for val in await self.eval_(g.iter, briefcase):
                        briefcase['variables'][g.target.id] = val
                        cond = True
                        for con in g.ifs:
                            cond = cond and await self.eval_(con, briefcase)
                        if cond:
                            result.append(await self.eval_(node.elt, briefcase))
            return result
        elif isinstance(node, ast.DictComp):
            result = {}
            for g in node.generators:
                if isinstance(g, ast.comprehension):
                    for val in await self.eval_(g.iter, briefcase):
                        briefcase['variables'][g.target.id] = val
                        cond = True
                        for con in g.ifs:
                            cond = cond and await self.eval_(con, briefcase)
                        if cond:
                            result[await self.eval_(node.key, briefcase)] = await self.eval_(node.value, briefcase)
            return result
        elif isinstance(node, ast.IfExp):
            if await self.eval_(node.test, briefcase):
                return await self.eval_(node.body, briefcase)
            else:
                return await self.eval_(node.orelse, briefcase)
        elif isinstance(node, ast.While):
            whendo1 = whendo(self.instance, briefcase['app'], node.test, node.body)
            self.universal_whendos.append(whendo1)
            self.exec_loop.add(whendo1)
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith('sequencer_'):
                sequencer = node.name.split('_')[1]
                self.variables[briefcase['app']][sequencer] = 0
                prefix = None
                for state in node.body:
                    prefix = state.test
                    for rule in state.body:
                        if isinstance(rule, ast.Assign) or isinstance(rule, ast.Continue) or isinstance(rule, ast.Expr):
                            whendo1 = whendo(self.instance, briefcase['app'], prefix, [rule])
                            self.universal_whendos.append(whendo1)
                            self.exec_loop.add(whendo1)
                        elif not isinstance(rule, ast.Pass):
                            whendo1 = whendo(self.instance, briefcase['app'], [prefix, rule.test], rule.body)
                            self.universal_whendos.append(whendo1)
                            self.exec_loop.add(whendo1)
                self.exec_loop.pending_signals.put_nowait([sequencer, self.instance, briefcase['app']])
            else:
                self.variables[briefcase['app']][node.name] = func(node.body, node.args)
        elif isinstance(node, ast.NameConstant):
            return node.value
        elif isinstance(node,  str) or isinstance(node, int) or isinstance(node, float):
            return node
        elif isinstance(node, ast.Tuple):
            rs = []
            for el in node.elts:
                rs.append(await self.eval_(el, briefcase))
            return tuple(rs)
        elif isinstance(node, ast.Set):
            return set([await self.eval_(r, briefcase) for r in node.elts])
        elif isinstance(node, ast.Expr):
            return await self.eval_(node.value, briefcase)
        elif isinstance(node, ast.JoinedStr):
            val = ""
            for exp in node.values:
                if isinstance(exp, ast.Constant):
                    val += await self.eval_(exp, briefcase)
                else:
                    val += str(await self.eval_(exp.value, briefcase))
            return val
        elif isinstance(node, ast.AugAssign):
            val = self.operators[type(node.op)](await self.eval_(node.target, briefcase),await self.eval_(node.value, briefcase))
            await self.assign(node.target, val, briefcase, [])
        elif isinstance(node, ast.Continue):
            return None
        elif isinstance(node, ast.Pass):
            return None
        else:
            raise Exception('unsupported type: ' + str(type(node)).split('.')[1].split("'")[0])
            # raise TypeError(node)

class whendo():
    def __init__(self, instance, app, when, do):
        self.when = when
        self.do = do
        self.done = False
        self.errors = [] # {'statement':'', 'error':''}
        self.error_count = 0
        self.instance = instance
        self.app = app
    def add_error(self, error):
        self.error_count+=1
        if error not in self.errors:
            self.errors.append(error)

class func():
    def __init__(self, body, params):
        self.body = body
        self.params = params

class _class():
    def __init__(self, body):
        self.body = body


class Node():
    def __init__(self, messages, name, gateway):
        self.type = None
        self.name = name
        self.messages = messages
        self.gateway = gateway
        self.ports = {}
        self.session = None
        self.discovery_complete = False

    def __iter__(self):
        self.iterobj = iter(self.ports)
        return self.iterobj

    def __next__(self):
        next(self.iterobj)

    def json(self):
        return json.dumps(self.ports)

    def __unicode__(self):
        return self.name + str(self.ports)

    def __repr__(self):
        return self.name + str(self.ports)

    def __str__(self):
        return self.name + str(self.ports)

    def __contains__(self, item):
        return item in self.ports

    def __getitem__(self, item):
        # self.messages.put_nowait(('{}:{} get {} {}:ee\n'.format(self.gateway, self.name, item, self.gateway), None))
        if item in self.ports:
            return self.ports[item]
        elif item == 'name':
            return self.name
        elif item == 'type':
            return self.type
        elif item == 'session':
            return self.session
        else:
            return None

    def __setitem__(self, key, value):
        if not self.session is None:
            self.messages.put_nowait(('{}:{} set {} {} session={} {}:ee'.format(self.gateway, self.name, key, json.dumps(value), self.session, self.gateway), None))
        else:
            self.messages.put_nowait(('{}:{} set {} {} {}:ee'.format(self.gateway, self.name, key, json.dumps(value), self.gateway), None))

    def set(self, key,value):
        self.ports[key] = value

    def settype(self, type):
        self.type = type

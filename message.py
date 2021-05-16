import json

class Message:
    def __init__(self, content):
        words = self.split(content)
        self.address_instance, self.address = words[0].split(':') if ':' in words[0] else ('', words[0])
        self.command = words[1] if len(words)>1 else None
        self.params = words[2:-1] if len(words)>2 else None
        self.port = words[2] if len(words)>=4 else None
        try:
            self.value = json.loads(words[3]) if len(words)>=5 else None
        except:
            self.value = None
        self.sender_instance, self.sender = words[-1].split(':') if ':' in words[-1] else ('', words[-1])

    def __str__(self):
        return self.address + ' ' + self.command + ' ' + ' '.join(p for p  in self.params) + (' ' if self.sender_instance=='' else f' :{self.sender_instance} ') + self.sender

    def split(self, s):
        def opposite(c):
            if c== '{': return '}'
            if c== '[': return ']'
            if c== '(': return ')'
            return  c

        s = s.replace('\\"', '&#34;')
        s = s.replace("\'", '&#39;')
        s = s.strip()
        tokens = []
        token = ''
        tokcount = 0
        sep = ''
        isparam = False
        for c in s:
            if c in [' ', '[', '(', '{', '"', "'"] and sep == '': # beginning of token?
                if len(token) != 0 and c == ' ': # is there a previous one?
                    if token == '=' or isparam: #  is this one a param?, then add to previous token
                        isparam = not isparam
                        tokens[-1]+= token
                        print(tokens[-1])
                    else:                       # else then a separate token
                        tokens.append(token)
                    token = ''                  # reset params
                    sep = ''
                    tokcount=0
                elif c!= ' ' and len(token)==0: # begin token
                    sep = c
                    tokcount+=1
                elif c!= ' ':             # continue token, ignore separators not preceded by spaces
                    token += c
            elif c in [' ', '[', '(', '{'] and c==sep:
                tokcount+=1
                token += c
            elif c in [']', ')', '}', '"'] and c == opposite(sep):
                tokcount-=1
                if tokcount == 0:
                    if token == '=' or isparam:
                        isparam = not isparam
                        tokens[-1]+= token
                    else:
                        tokens.append( sep + token + c)
                    token = ''
                    sep = ''
                else:
                    token += c
            else:
                token += c
        if token!='': tokens.append(token)
        if len(tokens) >= 2:
            tokens[-2] = tokens[-2].replace('&#34;', '\\"')
            tokens[-2] = tokens[-2].replace('&#39;', "\'")
        return tokens
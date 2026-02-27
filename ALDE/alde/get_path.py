"""Path utilities.

Maintainer contact: see repository README.
"""

import sys, os


class GetPath:
    
    """
    explanation:

    if f 'is' selectetd the file in path will returned, 
    if only parg (p) as, string formatted arg is given, the path will returned.
    Is w is selected the working directory will returned, is 
    'h' selected the home directory is returned. With any 'int'(i) is in path length,
    as argument, the part on int's postion will returned. 
    If sys.arg is given, get_path takes it's as first path argument from sys.arg[1],
    also with sys.arg as first argument
    you can adjust your needs with the second argument.  

    'p' -> returns path
    'f' -> returns file
    'w' -> returns working directory
    'h' -> returns home directory
    'i' -> returns part of path 
    
    """
    def __init__(self):
    
            self.pl:list = {'p':-1,'f':-1,
                            'w':-2,'h':1,
                            'i':"",'s':0
                            }
        
    def get_path(
            self,parg:str = None,
            opt:str = None) -> str:
      
            pfl:list = ['/']
            pfl1:list = ['/']
            pfl2:list = []

            if opt: 
                for op in self.pl:
                    if opt == op and opt == 's':   # special case for 's' wenn daunter varaiable '__file__' nicht verwendet wird
                        z = self.pl[op]
                        x = -1

                    elif opt == op:
                        x = self.pl[op]
                        z = 1
                    continue
           
            if (parg is not None):
                parg_1:str = str(parg).split('/')[1:-1]
                parg_2:str = str(parg).split()[z:]
               
                for pf1 in parg_1:
                    pfl1.append(f'{str(pf1).strip()}/')
                    if parg_2 == '':
                        ps = ''.join(pfl1)
                        return ps[z:x]
                
                if parg_2 != '':
                    for pf2 in parg_2:
                        pf3 = pf2.strip()
                        pfl2.append(f'{str(pf3).strip()}/')  
                    ps = ''.join(pfl1 + pfl2)
                return ps[0:x]

            elif len(sys.argv) >=1:
                arg = sys.argv[1]
                for pf in str(arg).split('/')[1:-1]:
                    pfl.append(f'{pf.strip()}/')   
                return os.path.join(*pfl)

    def _file(
            self,
            parg:str = None) -> str:
        
            if (parg is not None):
                parg_1:list = str(parg).split('/')
                pfl=['/']
                if parg_1:    
                    for pf in parg_1:
                        pfl.append(f'{str(pf).strip()}')
                    return pfl[-1]
            elif len(sys.argv) >=2:
                pfl:list = ['/']
                arg:sys = sys.argv[1]           
                for pf in str(arg).split('/'):      
                    pfl.append(f'{pf.strip()}/')           
                return str(pfl[-1])
    
    def _parent(
            self,
            parg:str = None
            ) -> str:
        
            parg_1:list = str(parg).split('/')
            pfl:list = ['/']
            if (parg is not None):    
                for pf in parg_1:
                    pfl.append(f'{str(pf).strip()}/')
                return os.path.join(*pfl[1:-2])
            elif len(sys.argv) >=2:
                arg:sys = sys.argv[1]
                for pf in str(arg).split('/'):
                    pfl.append(f'{pf.strip()}/')   
                return str(pfl[1:-2])
    
    def get_workdir(
            self,
            parg:str = None
            ) -> str:
        
            parg_1:list = str(parg).split('/')
            pfl:list = ['/']
            if (parg is not None):    
                for pf in parg_1:
                    pfl.append(f'{str(pf).strip()}')
                return os.path.join(*pfl)
            elif len(sys.argv) >=2:
                arg:sys = sys.argv[1]
                for pf in str(arg).split('/'):
                    pfl.append(f'{pf.strip()}/')   
                return str(pfl[-2])

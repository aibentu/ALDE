from __future__ import annotations
from pathlib import Path
from datetime import datetime
from chatclasscompletion  import ChatComEditor
from dotenv import load_dotenv
import os
import sys
from pysys_Cmd import sys_Cmd
from counter import Counter
 

class Caller():
        
    def __init__(self):
        count = Counter()
        count.increment()
        self._vnr = count._global_count
        BYdA = '%B %Y, %d %A'
        dmY = '%d%m%Y'
        hMs = '%H:%M:%S'

        self.nowTime = datetime.now()
        self.date_f1 = self.nowTime.strftime(BYdA)
        
        self.date_f2 = self.nowTime.strftime(dmY)
        self.time = self.nowTime.strftime(hMs) 
        self.unix_t = self.nowTime.timestamp()
        spLit = self.unix_t
        spLit = str(spLit).split('.')
        self.s_ID = f'{spLit[0]}{spLit[1]}'                 
        self.path_read = ""
        self.fileTl = "dbg"                                # first part of title file to write (example: "dbg")
        self.path:str = ""
        self.path = self.get_path()                        # get path from sys.arg[]/__file__ / ..
        
        self.file:str = ""
        self.file = self.get_file(parg = None)                        # get file_name from path 
        self.workdir = self.get_workdir()                  # path to current working directory
        self.path_new = ""                                 # get file from sys.arg[]
        self.dbg_file = ""
        self.dir = ""     
        print(f"path: {self.path}")
        print(f"file: {self.file}")
        print(f'working directory: {self.workdir}')
        if len(sys.argv) >=1: self.path_read = sys.argv[1] 
        else: self.path_read = ""

            


    def get_path(
            self,parg:str | None, 
            opt:str = str | None) -> str:
  
      """
      explanation:
  
      if f 'is' seletetd the file in path will returned, 
      if only parg (p) as, string formatted arg, is given the path will returned.
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
  
      x = 0
      p:str = -2
      f:str = -1
      w:str = ""
      h:str = 1
      i:str = ""
      
      self.pl:list={'p':0,'f':-1,'w':-2,'h':1,'i':""}
      
      
    def get_path(
            self,parg:str = None,
            opt:str = None) -> str:
    
            pfl:list = ['/']
            pfl1:list = ['/']
            pfl2:list = []
            if opt: 
                for op in self.pl:
                    if opt == op:
                        x = self.pl[op]
                    print(x)
                    continue
          
            if (parg != None):
                parg_1:str = str(parg).split('/')[1:-1]
                parg_2:str = str(parg).split()[1:]
                for pf1 in parg_1:
                    pfl1.append(f'{str(pf1).strip()}/')    
                for pf2 in parg_2:
                    pf3 = pf2.strip()
                pfl2.append(f'{str(pf3).strip()}/')  
                print(pfl1[0:])
                print(pfl2[0:])
                ps = ''.join(pfl1 + pfl2)
                return ps[0:x]
             #os.path.join(*pfl1,*pfl2)

            elif len(sys.argv) >=1:
                arg = sys.argv[1]
                for pf in str(arg).split('/')[1:-1]:
                    pfl.append(f'{pf.strip()}/')   
                return os.path.join(*pfl)
         
    def get_file(
            self,parg:str = None) -> str:
        if (parg != None):
            parg_1:list = str(parg).split('/')
            pfl=['/']
            if parg_1:    
                for pf in parg_1:
                    pfl.append(f'{str(pf).strip()}')
                return pfl[-1]
        elif len(sys.argv) >=2:
            pfl:list=['/']
            arg:sys = sys.argv[1]           
            for pf in str(arg).split('/'):      
             pfl.append(f'{pf.strip()}')           
            return pfl[-1]
    
    def get_workdir(
            self,parg:str = None) -> str:
        
        parg_1:list = str(parg).split('/')
        pfl=['/']
        if (parg != None):    
            for pf in parg_1:
                pfl.append(f'{str(pf).strip()}')
            return os.path.join(*pfl)
        elif len(sys.argv) >=2:
            arg:sys = sys.argv[1]
            for pf in str(arg).split('/'):
             pfl.append(f'{pf.strip()}/')   
            return pfl[-2]
    
    
    
    def _unique(self):             

        """returns a unique file_name 
        with title/  sequenz_number/date/unixtime
        params: titel -> str.
        only to use with with path tools from caller class"""                    
       
        try: 
         self.path_new = f"{self.path}{self.dir}" if self.get_workdir() != "dbgfile" else self.path
         print(f"new path:{ self.path_new}")
         self.dbg_file = f"{self.fileTl}_{self.date_f2}_{self._vnr}_{self.s_ID}"
         print(f"debuggig file:{ self.dbg_file}")
         print(f'pfad zum schreiben der datei {self.path_new}')
        except Exception as e:print(f"Error (error while building path or file): {e}")
             
    
    def __repr__(self):
        return (f"Caller(date='{self.date_f1}',"f"dateTime='{self.time}',"
                f"args='',unix_t='{self.unix_t}',"
                f"vn='{self._vnr}, path='{self.path_read}',"
                f"SessionID='{self.s_ID}',Originpath='{self.path}',"
                f"date'{self.date_f2}','filename'{self.file}")
    
class CallerDebugger(ChatComEditor,Caller):

    def __init__(self):
            self.cal = Caller()
            self.dir:str = "dbgfile/" 
            self._api_key = ChatComEditor._api_key
            print( f'pfad zum einlesen: {self.cal.path}{self.cal.file}')
            #print(f'pfad zum schreiben der datei {self.dir}')
            self.cont:str = ""
       
    
    def _unique(self):
       
            try: 
                self.path_new = f"{self.cal.path}{self.dir}" if self.cal.get_workdir() != "dbgfile" else self.path
                print(f"new path:{ self.path_new}")
                self.dbg_file = f"{self.cal.fileTl}_{self.cal.date_f2}_{self.cal._vnr}_{self.cal.s_ID}"
                print(f"debuggig file:{ self.dbg_file}")
                print(f'pfad zum schreiben der datei {self.path_new}')
            except Exception as e:print(f"Error (error while building path or file): {e}")
        
    
    def readwrite(self):


            try: 
                self.path_new = f"{self.cal.path}{self.dir}" if self.cal.get_workdir() != "dbgfile" else self.cal.path
                print(f"new path:{ self.path_new}")
                self.dbg_file = f"{self.cal.fileTl}_{self.cal.date_f2}_{self.cal._vnr}_{self.cal.s_ID}"
                print(f"debuggig file:{ self.dbg_file}")
                print(f'pfad zum schreiben der datei {self.path_new}')
            except Exception as e:print(f"Error (error while building path or file): {e}")
        
        
            try:
                with open(f'{self.path_new}{self.dbg_file}', 'w') as f:
                     f.write(f"# {self.cal.date_f1}\n\n# {self.cal.time}\n\n# Python3 run\n\n"
                    "# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––|\n"
                    "# requests are about code factoring or refactoring and          |\n"
                    "# debugging & writing a patch.                                  |\n"  
                    "# additional instructions in codeblock header                   |\n"
                    "# STDERR in file footer                                         |\n"
                    "# if not STDERR, just follow the instructions from codeblock    |\n"
                    "# header                                                        |\n"
                    "# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––|"
                    )
            except Exception as e:
             print(f"Error (file write): {e}")

            try:
             with open(f'{self.cal.path}{self.cal.file}', "r") as file:
              self.cont = file.read() 
            except Exception as e:print(f"Error (file read):{e}")

            try: 
            
             run = sys_Cmd
             capture_output = run.CmdSys(f"python3 {self.cal.path_read}")
             stdout = capture_output.stdout.decode("UTF-8")
             stderr = capture_output.stderr.decode("UTF-8")

             print(f"'''\n{stdout}\n'''\n\n'''\n{stderr}\n'''")

             with open(f'{self.path_new}{self.dbg_file}',"a") as f:
              f.write(
                "\n\n\n"
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "                                  CODE/SCRIPT                                                   \n"  
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "\n\n" + f"{self.cont}\n"     
                "'''\n\n\n\n"
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "                                    STDERR                                                      \n"
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "\n\n" + f"{stderr}\n"
                "'''\n\n\n\n"
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "                                    STDOUT                                                      \n"
                "|──────────────────────────────────────────────────────────────────────────────────────────────|\n"
                "\n\n" + f"{stdout}\n"
                "'''")
            except Exception as e: print(f"Error while executing subroutine {e}")

            try:
                chatcom = ChatComEditor(self._api_key, self.path_new, self.dbg_file, _input_text="")
                input_text = chatcom._readit()
                chatcom = ChatComEditor(self._api_key, self.path_new,self.dbg_file, _input_text=input_text)
                w = chatcom._response()
                chatcom._writeit(f'\n\n{w}')

            except Exception as e:print(f"Error (ChatCom ...): {e}")

call_debug = CallerDebugger()
call_debug.readwrite()
 


"""
  A counter that has
  * an instance-wide count   -> cls.instance_count
  * a process-wide, persistent count stored in _ctr_ -> Counter._global_count
""" 


class ReadEnv(): 

    def __init__(self,
        envar='OPENAI_API_KEY') -> None:
        envar
   
    @staticmethod
    def _read_env(envar) -> str:

        # must be set by user (avoid clear-text in source!)
        # 1) ----------------------------------------------------------------------------- –
        # Look for a .env file and load it once.
        # Try project root first, then the folder where ai_widget.py lives.

        root_dotenv = Path(__file__).resolve().parents[0] / ".env"
        local_dotenv = Path(__file__).with_suffix(".env")

        for f in (root_dotenv, local_dotenv):
            if f.exists():
                load_dotenv(f, override=False)   # read only the first one found
                break

        # 2) ----------------------------------------------------------------------------- –
        # Read the variable.  NOTE: the name must be a *string*.

        try:
         _api_key: str | None = os.getenv(envar)
        except Exception as e:print(f"ERROR: {e}")
        try: 
            load_dotenv() 
            _api_key = os.environ[envar]   # will KeyError if missing

        except:    # 3) ------------------------------------------------------------------ –
                   # Fail fast if the key is missing.
            raise RuntimeError(
                "OPENAI_API_KEY not found.\n"
                "Create a file called '.env' containing a line like:\n"
                '    OPENAI_API_KEY="sk-…"\n'
                "…or export it in your shell before launching the program:\n"
                "    export OPENAI_API_KEY=sk-…"
            ) 
    
        return _api_key    
    


# ------------- Call ReadEnc ---------------------------------------------- -

"""
read_api_key = ReadEnv()
ApiKey = read_api_key._read_api_key(envar)
print(ApiKey)
"""   


"""
Annotation

"""
  
class factory(ChatComEditor):  
    @classmethod
   
    def call(cls):
        instance = ChatComEditor()
        return instance
    
    def __init__(cls,path,file,input_text):
        super.__init__(path,file,input_text)
        file = ""
        path = ""
        w = input_text = ""
        cls.call().get_readedit(
            cls.call().get_response(
              cls.call().get_writeedit(
                 '\n\n\n'f"'''#{w}'''"
                 )
            )
        )

        #path = os.path.join(file)
    def debug():pass 
    def remanufacture():pass
    def build():pass
    def create():pass
        

    


class BatchFiles():
   
    def __init__(self, dir, batch_size):
        """
        Initialize BatchFiles processor.
        
        Args:
            dir: Directory path (can be relative or absolute, or empty string for current dir)
            batch_size: Number of files per batch
            
        Note: 
        - Uses current working directory as base (Path('.'))
        - To use script location instead: Path(__file__).resolve().parent / dir
        - To use custom parent dir: Path('./my_parent_dir') / dir
        """
        # Constructs path relative to current working directory
        # Note: Path('.') / '' results in Path('.'), making the conditional redundant,
        # but kept for clarity when dir is explicitly an empty string vs. None
        self.path = str(Path('.') / dir) if dir else str(Path('.'))
        self.batch_size = batch_size

    def _file_batches(self): 
      
      file_list:list = []
      for dateiname in os.listdir(self.path):
       print(dateiname)
       dateipfad = os.path.join(self.path, dateiname)
       print(dateipfad)
    # Überprüfen, ob es sich um eine Datei handelt (und keine Unterverzeichnisse etc.)
      if os.path.isfile(dateipfad):
        with open(dateipfad, 'r') as f:
            file = f.read()
            file_list.append()
            return file
       # print(file)

'''

dir = 'audit_files'

processbatch = BatchFiles(dir,'10')
print(processbatch._file_batches())
'''



"""
class CallerExecute:
    def __init__(self):
        super()
    
class Config:
    def __init__(self):
        Config

class Session:
    def __init__(self):
        Session

class Versioner():
    def __init__(self):
      Versioner

class Counter():
    def __init__(self):
      Counter

class ProcessingHistory():
    def __init__(self):
      ProcessingHistory 

"""

import subprocess
import time
from datetime import datetime, timedelta



class sys_Cmd():
    def __init__():
     
    
            __p_shell=False
            __p_proc=subprocess
            __p_cout=False
     
    def __gTpShell():__p_shell=True;pshell=__p_shell;return pshell
    def __gTpProcess():__p_proc=subprocess;pproc=__p_proc; return pproc 
    def __gTpCaptureOutput():__p_cout=True;pcout=__p_cout;return pcout 
    def __gTpArg1(t):pargs=__p_args=(f"sudo rtcwake -t {t}");pargs=__p_args;return pargs
    def __gTpArg2():__p_args=(f"systemctl suspend");pargs=__p_args;return pargs
    def __gTpArg(arg):command=(f"{arg}");return command
   
    
    
    def CmdSys(arg:str=None,t:str=None,s:bool=None):
            outp=[]
            if t and not s: out=(sys_Cmd.__gTpProcess().run(sys_Cmd.__gTpArg1(t),\
                  shell=sys_Cmd.__gTpShell(),\
                  capture_output=sys_Cmd.__gTpCaptureOutput()));outp.append(out);return outp[0]
           
            elif s and not t: out=sys_Cmd.__gTpProcess().run(sys_Cmd.__gTpArg2(),\
                  shell=sys_Cmd.__gTpShell(),\
                  capture_output=sys_Cmd.__gTpCaptureOutput());outp.append(out);return outp[0]
            
            elif s and t: 
                  out=(sys_Cmd.__gTpProcess().run(sys_Cmd.__gTpArg1(t),\
                  shell=sys_Cmd.__gTpShell(),\
                  capture_output=sys_Cmd.__gTpCaptureOutput()));outp.append(out);print(s,t)

                  out=sys_Cmd.__gTpProcess().run(sys_Cmd.__gTpArg2(),\
                  shell=sys_Cmd.__gTpShell(),\
                  capture_output=sys_Cmd.__gTpCaptureOutput());outp.append(out);return outp
                  
            elif arg: out=sys_Cmd.__gTpProcess().run(sys_Cmd.__gTpArg(arg),\
                  shell=sys_Cmd.__gTpShell(),\
                  capture_output=sys_Cmd.__gTpCaptureOutput());outp.append(out);return outp[0]

            else: pass
            print(outp)
                              

'''
# Example usage - replace with your own media file path:
# media_file = "path/to/your/audio.mp3"
# out = sys_Cmd.CmdSys(f'cvlc {media_file} --audio-visual glspectrum', check=True)
# print(out.stdout.decode("utf-8"), out.stderr.decode("utf-8"))
'''      

'''
out=sys_Cmd.CmdSys(' sudo apt install ffmpeg ')
print(out.stdout.decode("utf-8"),out.stderr.decode("utf-8"))
#print(sys_Cmd("atributx","atributy"))
#print(sys.atr1,sys.atr2)ip install pydub simpleaudio
'''
'''
data=sys_Cmd.CmdSys(arg=None,t="16:25",s=True)
data0=data[0].stdout
data1=data[0].stderr
'''
'''
data0_decoded=data0.decode("UTF-8")
data1_decoded=data1.decode("UTF-8")
print(f"{data0_decoded}{data1_decoded}{data}")
#{data.stdout.decode("UTF-8")}{data.stderr.decode("UTF-8")}")
'''













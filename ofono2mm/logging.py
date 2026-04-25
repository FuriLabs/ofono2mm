from inspect import currentframe
from time import time

def ofono2mm_print(message, verbose):
    if not verbose:
        return

    frame = currentframe()
    try:
        caller_frame = frame.f_back
        if not caller_frame:
            print(f"{time()} {message}", flush=True)
            return

        if 'self' in caller_frame.f_locals:
            cls = caller_frame.f_locals['self']
            cls_name = cls.__class__.__name__

            if hasattr(cls, 'modem_name'):
                obj_path = getattr(cls, 'modem_name', 'Unknown')
            elif hasattr(cls, 'voicecall'):
                obj_path = getattr(cls, 'voicecall', 'Unknown')
            else:
                obj_path = 'Unknown'

            func_name = caller_frame.f_code.co_name
            full_message = f"{cls_name}({obj_path}).{func_name}: {message}"
        else:
            func_name = caller_frame.f_code.co_name
            full_message = f"{func_name}: {message}"

        print(f"{time()} {full_message}", flush=True)
    finally:
        del frame

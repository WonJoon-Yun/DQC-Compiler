class _Dbg:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None
dbg = _Dbg()
def __getattr__(name):
    return lambda *args, **kwargs: None
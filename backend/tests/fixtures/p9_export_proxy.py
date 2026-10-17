class ExportProxy:
    """Keep the existing verified companion for both images, including rollback."""
    def __init__(self,release,binding,patch):
        self._release=release;self._binding=binding;self._patch=patch
    def __getattr__(self,name):return getattr(self._release,name)
    def compose(self,path,name):
        require_pins()
        command=self._release.compose(path,name)
        if name=='engine' and Path(path).name in ('naver-'+self._patch.OLD_COMMIT,'naver-'+self._patch.TARGET_COMMIT):
            _,folder,_=self._binding.h._prepared(self._binding.receipt)
            command=command+['-f',str(folder/self._binding.h.COMPANION)]
        return command
    def verify_exports(self):
        require_pins()
        return self._binding.operation(lambda:self._binding.h.verify(self._binding.receipt,command=self._binding.command))

"""Keep exact byte comparisons while making failure records JSON serializable."""
import hashlib
from common.checks import Checks as BaseChecks

class Checks(BaseChecks):
    def equal(self,actual,expected,category,detail):
        if isinstance(actual,bytes) and isinstance(expected,bytes):
            mismatch=next((i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b),None)
            info=dict(item=detail,actual_bytes=len(actual),expected_bytes=len(expected),first_mismatch=mismatch,
                      actual_sha256=hashlib.sha256(actual).hexdigest(),expected_sha256=hashlib.sha256(expected).hexdigest())
            if mismatch is not None:info.update(actual=actual[mismatch],expected=expected[mismatch])
            self.require(actual==expected,category,info)
        else:super().equal(actual,expected,category,detail)

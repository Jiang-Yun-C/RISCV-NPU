"""Recompute frozen Q96 constants independently at 180 decimal digits."""
import math,re
from decimal import Decimal,localcontext,ROUND_HALF_EVEN
from pathlib import Path

def verify():
    with localcontext() as ctx:
        ctx.prec=180
        expected=[int((Decimal(2)**96/Decimal(math.factorial(k))).to_integral_value(rounding=ROUND_HALF_EVEN)) for k in range(22)]
        ln2=int((Decimal(2).ln()*Decimal(2)**96).to_integral_value(rounding=ROUND_HALF_EVEN))
    root=Path(__file__).resolve().parents[2];text=(root/'variants/opt11/rtl/sfu/nx_opt11_exp.sv').read_text()
    actual=[int(v,16) for _,v in re.findall(r"5'd(\d+):coefficient=97'h([0-9a-f]+)",text)]
    if actual!=expected or int(re.search(r"LN2=104'h([0-9a-f]+)",text)[1],16)!=ln2:raise ValueError('RTL constant mismatch')
    return dict(coefficients=len(expected),ln2=hex(ln2),precision_decimal_digits=180)
if __name__=='__main__':print(verify())

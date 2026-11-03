"""twinkle_v1: four-board-LED rhythm, 120 BPM, one bounded cycle."""
from twinkle_plan import plan,play
NAME='twinkle_v1'
def build(arguments):
    if arguments!={'effect':'twinkle','bpm':120,'repeat':1}:raise ValueError('Unsupported package arguments')
    result=plan(120,1);result['source']='VERIFIED_MODEL_TOKEN_TO_REGISTERED_CODE_PACKAGE';return result
def run(link,music,stop):
    return play(link,music,stop)

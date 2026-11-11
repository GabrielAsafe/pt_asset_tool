from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from legacy_text import lex_bytes, decode_atom
from source_tokens import load_source_token_maps

def test_cp949_token():
    raw='*출연자 "테스트" 20'.encode('cp949')
    t=lex_bytes(raw)
    assert t[0].text=='*출연자' and t[1].text=='테스트' and t[2].text=='20'

def test_western_atom():
    text,enc=decode_atom('Informação'.encode('cp1252'))
    assert text=='Informação' and enc=='cp1252'

def test_source_maps(source_root:Path):
    maps=load_source_token_maps(source_root)
    assert maps['spawn']['*출연자'.encode('cp949')]=='actor'
    assert maps['character']['*이름'.encode('cp949')]=='name'
    assert maps['item']['*코드'.encode('cp949')]=='code'

def main():
    test_cp949_token();test_western_atom();test_source_maps(Path(__file__).resolve().parents[3])
    print('PASS content_port tests')
if __name__=='__main__': main()

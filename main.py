import argparse
from typing import Dict, List, Tuple
from string import ascii_lowercase, printable

parser = argparse.ArgumentParser(description='lzw compression, input data should only contain arabic numbers, spaces, and lowercase alphabets')
parser.add_argument('--input', required=True, type=str, help='input file')
args = parser.parse_args()

def initialize() -> Tuple[Dict, List]:
  # Construct a default table
  table: Dict[str, str] = dict()
  for c in ascii_lowercase:
    table[c] = c
  for c in range(0, 10):
    table[str(c)] = str(c)
  table[' '] = ' '

  defaults = set(table.keys())
  free_list: List[str] = list()
  for c in printable:
    if c not in defaults:
      free_list.append(c)
  return (table, free_list)

def compress(istr: str) -> str:
  (table, free_list) = initialize()

  # p : previous character
  # c : current character
  # table : character -> code mapping
  ostr = ""
  p = istr[0]

  # - Append c to p until pc is not in the table.
  # - When (p + c) is not in the table, add table[p] to the output string, 
  #   and add (p + c) to the table.
  for idx in range(1, len(istr)):
    c = istr[idx]
    pc = p + c
    if pc in table.keys():
      p = pc
    else:
      ostr = ostr + table[p]
      p = c
      if len(free_list) > 0:
        table[pc] = free_list[0]
        free_list.pop(0)
  ostr = ostr + table[p]
  return ostr

def decompress(istr: str) -> str:
  (table, free_list) = initialize()

  # pcode : previous code
  # ccode : current code
  # table : code -> character mapping
  # c : first character among the list of current characters  (s[0])

  # pcode           ccode
  # table[pcode]    s[0], s[1]...
  # (table[pcode]   s[0]) -> new entry to add to the table
  pcode = istr[0]
  ostr = table[pcode]
  c = ostr[0]

  # - When ccode is in the table, great, just use it
  # - When ccode is not in the table
  #   - ccode must have been built from pcode and current character
  # - As long as we have space, add the new pattern to the table
  for idx in range(1, len(istr)):
    ccode = istr[idx]
    if ccode not in table.keys():
      s = table[pcode] + c
    else:
      s = table[ccode]
    c = s[0]
    if len(free_list) > 0:
      table[free_list[0]] = table[pcode] + c
      free_list.pop(0)
    ostr = ostr + s
    pcode = ccode
  return ostr

def test(raw_str: str) -> bool:
  comp_str   = compress(raw_str)
  decomp_str = decompress(comp_str)
  if (raw_str != decomp_str):
    return False
  else:
    return True

def main():
  with open(args.input, 'r') as file:
    data = file.read().replace('\n', '')
    if test(data):
      print('LZW success')
    else:
      print('LZW failed')

if __name__ == "__main__":
  main()

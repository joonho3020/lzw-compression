from pathlib import Path
from typing import List, Dict
import argparse
import numpy as np

parser = argparse.ArgumentParser(description='snappy decompressor')
parser.add_argument('--comp-file', type=str, required=True, help='compressed input file')
parser.add_argument('--raw-file', type=str, required=True, help='raw file')
args = parser.parse_args()

def read_file(file: Path) -> List[int]:
  output: List[int] = list()
  with open(file, 'r') as f:
    output = np.fromfile(f, dtype=np.uint8)
  return output

# val[start:end]
def slice(val: int, start: int, end: int) -> int:
  nbits = end - start + 1
  mask = (1 << nbits) - 1
  return (val >> start) & mask

def snappy_decompress(compressed_bytes: List[int]) -> List[int]:
  decompressed_bytes: List[int] = list()

  # Ignore preamble for now
  idx: int = 0
  while idx < len(compressed_bytes):
    print(f'idx: {idx}')
    tag = compressed_bytes[idx]
    elem_type = slice(tag, 0, 1)
    upper_tag = slice(tag, 2, 7)
    # Literal
    if elem_type == 0:
      lit_len = 0
      if upper_tag < 60:
        lit_len = upper_tag + 1
        idx += 1
      else:
        extra_bytes = (upper_tag - 60) + 1
        for x in range(extra_bytes):
          b = compressed_bytes[idx + x + 1]
          lit_len += b * (2**x)
        idx += (extra_bytes + 1)
      print(f'literal litlen: {lit_len} compressed_bytes: {compressed_bytes[idx:idx+lit_len]}')
      decompressed_bytes.extend(compressed_bytes[idx:idx+lit_len])
      idx += lit_len
    # Copy
    else:
      # Copy with 1-byte offset
      if elem_type == 1:
        copy_len = slice(upper_tag, 0, 2) + 4
        offset = (slice(upper_tag, 3, 7) << 8) + compressed_bytes[idx + 1]
        idx += 2
      # Copy with 2-byte offset
      elif elem_type == 2:
        copy_len = upper_tag + 1
        offset = compressed_bytes[idx + 1] + \
                 (compressed_bytes[idx + 2] << 8)
        idx += 3
      # Copy with 4-byte offset
      elif elem_type == 3:
        copy_len = upper_tag + 1
        offset = compressed_bytes[idx + 1] + \
                 (compressed_bytes[idx + 2] << 8) + \
                 (compressed_bytes[idx + 3] << 16) + \
                 (compressed_bytes[idx + 4] << 24)
        idx += 5
      else:
        copy_len = 0
        offset = 0
        assert(f'Unexpected elem_type {elem_type}')

      print(f'copy offset: {offset} copy_len: {copy_len}')
      while copy_len > offset:
        copy_data = decompressed_bytes[-offset:]
        decompressed_bytes.extend(copy_data)
        copy_len -= offset
        offset += offset
        print(f'copy_data: {copy_data}')

      copy_data = decompressed_bytes[-offset:-offset+copy_len]
      decompressed_bytes.extend(copy_data)
      print(f'copy_data: {copy_data}')
  return decompressed_bytes

def main():
  compressed_bytes = read_file(Path(args.comp_file))
  raw_bytes = read_file(Path(args.raw_file))

  print(compressed_bytes)
  print(raw_bytes)

  decompressed = snappy_decompress(compressed_bytes[1:])
  for (i, rb) in enumerate(raw_bytes):
    if decompressed[i] != rb:
      print(f'mismatch on byte {i} {decompressed[i]} != {rb}')
      exit(1)
  print(f'decompression successful')

if __name__=="__main__":
  main()

import Path
from typing import List, Dict

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
      decompressed_bytes.extend(compressed_bytes[idx:idx+lit_len])
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
        offset = (compressed_bytes[idx + 1] << 8) + compressed_bytes[idx + 2]
        idx += 3
      # Copy with 4-byte offset
      elif elem_type == 3:
        copy_len = upper_tag + 1
        offset = (compressed_bytes[idx + 1] << 24) + \
                 (compressed_bytes[idx + 2] << 16) + \
                 (compressed_bytes[idx + 3] <<  8) + \
                 compressed_bytes[idx + 4]
        idx += 5
      else:
        copy_len = 0
        offset = 0
        assert(f'Unexpected elem_type {elem_type}')
      copy_data = decompressed_bytes[-offset-copy_len:-offset]
      decompressed_bytes.extend(copy_data)
  return decompressed_bytes

def main():
  print('hello main')

if __name__=="__main__":
  main()

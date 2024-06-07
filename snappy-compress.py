
from pathlib import Path
from typing import List, Tuple
import argparse
import numpy as np

from snappy_decompress import read_file, snappy_decompress_full

parser = argparse.ArgumentParser(description='snappy compressor')
parser.add_argument('--raw-file', type=str, required=True, help='raw file')
args = parser.parse_args()

HASHTABLE_ADDR_BITS = 14
HASHTABLE_ENTRIES   = 1 << HASHTABLE_ADDR_BITS
HASHTABLE_ADDR_MASK = HASHTABLE_ENTRIES - 1
HASHTABLE_MAGIC_NUMBER = 0x1e35a7bd

def hash_fn(four_byte_input: int) -> int:
  """
  inline uint32_t HashBytes(uint32_t bytes, uint32_t mask) {
      constexpr uint32_t kMagic = 0x1e35a7bd;
      return ((kMagic * bytes) >> (32 - kMaxHashTableBits)) & mask;
  }
  """
  return ((HASHTABLE_MAGIC_NUMBER * four_byte_input) >> (32 - HASHTABLE_ADDR_BITS)) & HASHTABLE_ADDR_MASK

def slice_to_int(slice_in: List[int]) -> int:
  if len(slice_in) != 4:
    new_slice = [0, 0, 0, 0]
    for x in range(len(slice_in)):
      new_slice[x] = slice_in[x]
    slice_in = new_slice

  a = 0
  a |= slice_in[0]
  a |= slice_in[1] << 8
  a |= slice_in[2] << 16
  a |= slice_in[3] << 24
  return a

def int_to_slice(int_in: int) -> List[int]:
  out = []
  out.append(int_in & 0xFF)
  int_in >>= 8
  out.append(int_in & 0xFF)
  int_in >>= 8
  out.append(int_in & 0xFF)
  int_in >>= 8
  out.append(int_in & 0xFF)
  return out

class HashTable:
  table: List[int]

  def __init__(self):
    self.table = [-1 for _ in range(HASHTABLE_ENTRIES)]

  def lookup(self, four_bytes: List[int]) -> int:
    four_bytes_int = slice_to_int(four_bytes)
    hval = hash_fn(four_bytes_int)
    return self.table[hval]

  def set_table(self, four_bytes: List[int], abs_addr: int) -> None:
    four_bytes_int = slice_to_int(four_bytes)
    hval = hash_fn(four_bytes_int)
    self.table[hval] = abs_addr

class HistoryBuffer:
  history: List[int]

  def __init__(self):
    self.history = [0 for _ in range(64 << 10)]

  def insert(self, history_bytes: List[int]) -> None:
    c = history_bytes.copy()
    c.reverse()
    length = len(c)
    self.history = c + self.history[:-length]

  def check_match_len(self, input_stream: List[int], offset: int) -> Tuple[int, bool]:
    assert(offset >= 0)
    h = self.history[:offset].copy()
    h.reverse()

    assert(len(h) == offset)

    min_len = min(len(h), len(input_stream))
    match_length = 0
    for idx in range(min_len):
      if h[idx] != input_stream[idx]:
        return (match_length, False)
      match_length += 1
    return (match_length, min_len == offset)

class SnappyCompressor:
  history_buffer: HistoryBuffer
  hash_table: HashTable
  cur_ptr: int
  skip: int
  window_bytes: int
  literal_buffer: List[int]

  def __init__(self) -> None:
    self.history_buffer = HistoryBuffer()
    self.hash_table = HashTable()
    self.window_bytes = 16
    self.reset()

  def reset(self) -> None:
    self.cur_ptr = 0
    self.skip = 32
    self.literal_buffer = list()

  def varint_encoding(self, x: int) -> List[int]:
    varint_mask = (1 << 7) - 1
    varint: List[int] = list()
    while x > 0:
      next_x = x >> 7
      upper_bit = 1 if (next_x > 0) else 0
      lower_bits = x & varint_mask
      varint.append((upper_bit << 7) | lower_bits)
      x = next_x
    return varint

  def emit_literal_tag(self, litlen: int) -> List[int]:
    tag: List[int] = list()
    if litlen <= 60:
      tag += bytes([(litlen-1) << 2])
    elif litlen <= 256:
      tag += bytes([(60 << 2)])
      tag += bytes([litlen - 1])
    elif litlen <= 1024:
      tag += bytes([(61 << 2)])
      tag += bytes([(litlen - 1) & 0xFF])
      tag += bytes([((litlen - 1) >> 8) & 0xFF])
    else:
      tag += bytes([(63 << 2)])
      tag += bytes([(litlen - 1) & 0xFF])
      tag += bytes([((litlen - 1) >> 8) & 0xFF])
      tag += bytes([((litlen - 1) >> 16) & 0xFF])
      tag += bytes([((litlen - 1) >> 24) & 0xFF])
    return tag

  def emit_copy_command(self, offset: int, match_len: int) -> List[int]:
    copy_command: List[int] = list()
    if match_len <= 11 and match_len >= 4 and offset <= 2047:
      copy_command += bytes([
          1 | (((match_len - 4) & 0x7) << 2) | (((offset >> 8) & 0x7) << 5),
          offset & 0xFF
      ])
    elif match_len <= 64 and match_len >= 1 and offset <= 65535:
      copy_command += bytes([
          1 | (((match_len - 1) & 0x3F) << 2),
          offset & 0xFF,
          (offset >> 8) & 0xFF
      ])
    else:
      copy_command += bytes([
          1 | (((match_len - 1) & 0x3F) << 2),
          offset & 0xFF,
          (offset >> 8) & 0xFF,
          (offset >> 16) & 0xFF,
          (offset >> 24) & 0xFF
      ])
    return copy_command

  def compress_input(self, raw_input_file: List[int]) -> List[int]:
    compressed_output: List[int] = list()
    self.reset()

    compressed_output += self.varint_encoding(len(raw_input_file))

    while self.cur_ptr + 3 < len(raw_input_file):
      remaining_bytes = len(raw_input_file) - self.cur_ptr
      next_advance_bytes = min(self.window_bytes, self.skip >> 5)

      cur_4Bytes = raw_input_file[self.cur_ptr:self.cur_ptr+4]
      cur_windowBytes = raw_input_file[self.cur_ptr:self.cur_ptr + min(remaining_bytes, self.window_bytes)]

      # Update the hashtable with the current 4 bytes & perform the hashtable lookup
      self.hash_table.set_table(cur_4Bytes, self.cur_ptr)
      history_abs_addr = self.hash_table.lookup(cur_4Bytes)

      # Literal
      if history_abs_addr == -1:
        # Add to history buffer & literal buffer
        self.history_buffer.insert(raw_input_file[self.cur_ptr:self.cur_ptr + next_advance_bytes])
        self.literal_buffer +=     raw_input_file[self.cur_ptr:self.cur_ptr + next_advance_bytes]

        self.cur_ptr += next_advance_bytes
        self.skip += next_advance_bytes
        continue

      offset = self.cur_ptr - history_abs_addr
      (match_len, continue_history_lookup) = self.history_buffer.check_match_len(cur_windowBytes, offset)

      # HashTable collision, fake match
      if match_len == 0:
        self.history_buffer.insert(raw_input_file[self.cur_ptr:self.cur_ptr + next_advance_bytes])
        self.literal_buffer +=     raw_input_file[self.cur_ptr:self.cur_ptr + next_advance_bytes]

        self.cur_ptr += next_advance_bytes
        self.skip += next_advance_bytes
        continue

      # Match, we have a copy command

      # - emit any literals
      compressed_output += self.emit_literal_tag(len(self.literal_buffer))
      compressed_output += self.literal_buffer
      self.literal_buffer = list()

      # End of a match, ship the copy command at this point
      if match_len != self.window_bytes and not continue_history_lookup:
        self.history_buffer.insert(cur_windowBytes[:match_len])
        compressed_output += self.emit_copy_command(offset, match_len)

        self.cur_ptr += match_len
        self.skip = 32
        continue

      # advance the cur_ptr and the abs address to perform the lookup
      self.cur_ptr += match_len
      history_abs_addr += match_len
      self.history_buffer.insert(cur_windowBytes[:match_len])

      # Need to keep advancing the cur_ptr until there is a mismatch
      while self.cur_ptr < len(raw_input_file):
        remaining_bytes2 = len(raw_input_file) - self.cur_ptr
        cur_windowBytes2 = raw_input_file[self.cur_ptr:self.cur_ptr + min(remaining_bytes2, self.window_bytes)]

        offset2 = self.cur_ptr - history_abs_addr
        (match_len2, continue_history_lookup2) = self.history_buffer.check_match_len(cur_windowBytes2, offset2)

        match_len += match_len2
        history_abs_addr += match_len2
        self.cur_ptr += match_len2

        if match_len2 == 0:
          break

        self.history_buffer.insert(cur_windowBytes2[:match_len2])

        if match_len2 != self.window_bytes and not continue_history_lookup2:
          break

      # At this point the match finished, ship the copy command
      compressed_output += self.emit_copy_command(self.cur_ptr - history_abs_addr, match_len)

      self.skip = 32
      self.hash_table.set_table(raw_input_file[self.cur_ptr-1:self.cur_ptr-1+4], self.cur_ptr-1)

    # Some literals remaining in the end
    if self.cur_ptr != len(raw_input_file):
      self.literal_buffer += raw_input_file[self.cur_ptr:]

    # Ship the remaining literals
    if len(self.literal_buffer) != 0:
      compressed_output += self.emit_literal_tag(len(self.literal_buffer))
      compressed_output += self.literal_buffer
      self.literal_buffer = list()

    return compressed_output


def main():
  raw_bytes = read_file(Path(args.raw_file))
  print(type(raw_bytes))

  compressor = SnappyCompressor()
  compressed_bytes = compressor.compress_input(raw_bytes.tolist())

  decompressed_bytes = snappy_decompress_full(compressed_bytes)

  for (i, rb) in enumerate(raw_bytes):
    if decompressed_bytes[i] != rb:
      print(f'mismatch on byte {i} {decompressed_bytes[i]} != {rb}')
      exit(1)
  print(f'compression successful')

if __name__ == "__main__":
  main()

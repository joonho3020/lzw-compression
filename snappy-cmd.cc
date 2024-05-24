#include <fstream>
#include <iostream>
#include <sstream>
#include "./snappy-install/usr/local/include/snappy.h"

int main(int argc, char** argv) {
  if (argc < 3) {
    printf("Usage: ./snappy-cmd <file to compress> <compressed file>\n");
    exit(1);
  }

  char* file_to_compress = argv[1];
  char* compressed_file_path = argv[2];

  std::ifstream in_file;
  in_file.open(file_to_compress);

  std::stringstream ss;
  ss << in_file.rdbuf();
  std::string str_file = ss.str();

  std::string compressed_str;
  snappy::Compress(str_file.c_str(), str_file.size(), &compressed_str);

  std::ofstream compressed_file(compressed_file_path);
  compressed_file << compressed_str;
  compressed_file.close();


  return 0;
}

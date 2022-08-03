import sys
import os
import glob
from argparse import ArgumentParser
from compression_algorithms import Lzop, Lzma, Lz4, Gzip, Bzip2, Snappy


def extract_files(directory: str, search_pattern: str):
    assert os.path.exists(directory)
    return [file for file in glob.glob(directory + search_pattern, recursive=True)]


def main():
    parser = ArgumentParser(description='Recursively apply commands to files in directory and keep statistics.')
    parser.add_argument('--dir', help='Directory to look for files.')
    parser.add_argument('--mode', help='Debug or Release')
    parser.add_argument('--level', help="Compression level")
    parser.add_argument('--compiler', help='gcc11 or clang14')
    parsed = parser.parse_args(sys.argv[1:])
    path = parsed.dir
    level = int(parsed.level)
    compiler = str(parsed.compiler).lower()
    mode = str(parsed.mode).upper()

    files = extract_files(path, '/**/*.o')

    # algorithms = [alg(files, level) for alg in [Lzop, Lzma, Lz4, Gzip, Bzip2] for level in list(range(1, 10))]
    algorithms = [alg(files, level) for alg in [Lzop, Lzma, Gzip] for level in list(range(1, 10))]
    algorithms += [Snappy(files)]

    for algorithm in algorithms:

        if algorithm.flags['compression_level'] != '':
            compression_level = algorithm.flags['compression_level'][-1]
        else:
            compression_level = '0'

        print(f"Benchmarking method {algorithm.name} with compression level {compression_level}")
        result = algorithm.apply()

        with open(f"benchmark_{compiler}_{algorithm.name}_{mode}_{compression_level}.csv", 'w') as report:
            header = "Filename, Size_Original, Size_Compressed, Size_Ratio, Time_Compress, Time_Decompress"
            report.write(header + '\n')
            for file, stats in result.items():
                report.write(', '.join([file] + [str(stat) for stat in stats]) + '\n')

        print('Benchmark completed.')


if __name__ == '__main__':
    main()


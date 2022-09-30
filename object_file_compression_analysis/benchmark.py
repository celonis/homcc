import sys
import os
import glob
from argparse import ArgumentParser
from compression_algorithms import Lzop, Lzma, Lz4, Gzip, Bzip2, Snappy


def get_compressor(algorithm_name: str):
    return {
        'lzop': Lzop,
        'lzma': Lzma,
        'lz4': Lz4,
        'gzip': Gzip,
        'bzip2': Bzip2,
        'snappy': Snappy
    }[algorithm_name.lower()]


def extract_files(directory: str, search_pattern: str):
    assert os.path.exists(directory)
    return [file for file in glob.glob(directory + search_pattern, recursive=True)]


def main():

    parser = ArgumentParser(description='Recursively apply commands to files in directory and keep statistics.')
    parser.add_argument('--dir', help='<Required> Directory to look for files', required=True)
    parser.add_argument('--mode', help='<Required> Debug or Release', required=True)
    parser.add_argument('--level', help='<Required> Compression level', required=True)
    parser.add_argument('--compiler', help='<Required> gcc11 or clang14', required=True)
    parser.add_argument('--algorithm', nargs='+', help='<Required> Name(s) of compression algorithms separated by space', required=True)

    parsed = parser.parse_args(sys.argv[1:])

    path = parsed.dir
    level = int(parsed.level)
    compiler = str(parsed.compiler).lower()
    mode = str(parsed.mode).upper()

    files = extract_files(path, '/**/*.o')
    algorithms = [get_compressor(alg)(files, level) for alg in parsed.algorithm]

    for algorithm in algorithms:

        if algorithm.flags['compression_level'] != '':
            compression_level = algorithm.flags['compression_level'][-1]
        else:
            compression_level = '0'

        print(f"Benchmarking method {algorithm.name} with compression level {compression_level}")
        result = algorithm.apply()

        report_name = f"benchmarks/{compiler}_{mode}_{algorithm.name}_{compression_level}.csv"
        os.makedirs(os.path.dirname(report_name), exist_ok=True)

        with open(report_name, 'w') as report:
            header = "Filename,Size_Original,Size_Compressed,Size_Ratio,Time_Compress,Time_Decompress"
            report.write(header + '\n')
            for file, stats in result.items():
                report.write(', '.join([file] + [str(stat) for stat in stats]) + '\n')

        print('Benchmark completed.')


if __name__ == '__main__':
    main()


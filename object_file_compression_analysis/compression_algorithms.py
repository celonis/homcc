from typing import Callable
from compression_utils import compress_decompress_implicit, compress_decompress_explicit


class Compressor:
    '''
    :param compressor_name: The name of the compression algorithm
    :param file_extension: The extension to be appended to filename as suffix after compression
    :param procedure_function: A function that returns timings and size information of the algorithm
    :param flags: A dictionary containing the system command and flags for (de)compression
    :param files: A list of files to (de)compress and benchmark
    '''

    def __init__(self,
                 compressor_name: str,
                 file_extension: str,
                 procedure_function: Callable[[str, str, dict], tuple],
                 flags: dict,
                 files: list):
        self.name = compressor_name
        self.extension = file_extension
        self.files = files
        self.flags = flags
        self.procedure = procedure_function

    def apply(self):
        result = dict()
        for file in self.files:
            result[file] = self.procedure(file, self.extension, self.flags)
            print(f"Completed ({self.name} {self.flags['compression_level']}) {file}")
        return result


class Lzma(Compressor):
    def __init__(self, files: list, compression_level=1):
        flags = {'shell_command': 'lzma', 'compress': '', 'decompress': '--decompress',
                 'keep': '--keep', 'force': '--force', 'compression_level': f'-{compression_level}'}
        super(Lzma, self).__init__('lzma', 'lzma', compress_decompress_implicit, flags, files)


class Gzip(Compressor):
    def __init__(self, files: list, compression_level=1):
        flags = {'shell_command': 'gzip', 'compress': '', 'decompress': '--decompress',
                 'keep': '--keep', 'force': '--force', 'compression_level': f'-{compression_level}'}
        super(Gzip, self).__init__('gzip', 'gz', compress_decompress_implicit, flags, files)


class Bzip2(Compressor):
    def __init__(self, files: list, compression_level=1):
        flags = {'shell_command': 'bzip2', 'compress': '', 'decompress': '--decompress',
                 'keep': '--keep', 'force': '--force', 'compression_level': f'-{compression_level}'}
        super(Bzip2, self).__init__('bzip2', 'bz2', compress_decompress_implicit, flags, files)


class Lzop(Compressor):
    def __init__(self, files: list, compression_level=1):
        flags = {'shell_command': 'lzop', 'compress': '', 'decompress': '--decompress',
                 'keep': '--keep', 'force': '--force', 'compression_level': f'-{compression_level}'}
        super(Lzop, self).__init__('lzop', 'lzo', compress_decompress_implicit, flags, files)


class Lz4(Compressor):
    def __init__(self, files: list, compression_level=1):
        flags = {'shell_command': 'lz4', 'compress': '', 'decompress': '-d',
                 'keep': '-k', 'force': '-f -z', 'compression_level': f'-{compression_level}'}
        super(Lz4, self).__init__('lz4', 'lz4', compress_decompress_explicit, flags, files)


class Snappy(Compressor):
    def __init__(self, files: list):
        flags = {'shell_command': 'python3.9 -m snappy', 'compress': '-c',
                 'decompress': '-d', 'keep': '', 'force': '', 'compression_level': ''}
        super(Snappy, self).__init__('snappy', 'snappy', compress_decompress_explicit, flags, files)



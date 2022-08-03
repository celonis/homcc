from timeit import default_timer as timer
import os


def compress(flags: dict, input_filename, output_filename=None) -> float:
    '''Executes the specified compression command with the given flags.'''
    command = ' '.join([
        flags['shell_command'], flags['keep'], flags['force'],
        flags['compression_level'], flags['compress'], input_filename])

    if output_filename is not None:
        command += ' ' + output_filename

    time_start = timer()
    if os.system(command) != 0:
        print('Something went wrong when executing command ' + command)
    time_end = timer()

    return time_end - time_start


def decompress(flags: dict, input_filename, output_filename=None) -> float:
    '''Executes the specified decompression command with the given flags.'''
    command = ' '.join([
        flags['shell_command'], flags['keep'], flags['force'],
        flags['compression_level'], flags['decompress'], input_filename])

    if output_filename is not None:
        command += ' ' + output_filename

    time_start = timer()
    os.system(command)
    time_end = timer()

    return time_end - time_start


def compare_file_sizes(input_filename, output_filename) -> tuple:
    '''
    Returns a tuple with the following content
    [0]: size of the input file in bytes
    [1]: size of the output file in bytes
    [2]: size difference percentage based on the size of the input file
    '''
    size_original = os.path.getsize(input_filename)
    size_compressed = os.path.getsize(output_filename)
    compression_ratio = 100 * (size_original-size_compressed) / size_original
    return size_original, size_compressed, compression_ratio


def rename_file(old_filename, new_filename):
    os.rename(old_filename, new_filename)


def compress_decompress_implicit(file: str, extension: str, flags: dict):
    '''
    Compresses and decompresses the given file with the specified flags.
    This method should be used for algorithms, whose (de)compression command 
    does not support passing an output filename as parameter.

    Example: 'lzop input.txt' will always generate the file input.txt.lzo as output,
    and when decompressing it expectes a file with .lzo extension, which is removed 
    after the decompression. That is, 'lzop --decompress input.txt.lzo' always
    generates the file 'input.txt'. This is referred to as implicit naming.

    When called with the --keep and --force flags, this function generates 
    two additional files input.copy and input.extension. The first one should be
    identical to the original input file, and the latter is the compressed data.
    '''
    filename_0 = file
    filename_1 = f'{file}.{extension}'
    filename_2 = f'{file}.copy.{extension}'

    time_compress = compress(flags, filename_0)
    size_information = compare_file_sizes(filename_0, filename_1)
    rename_file(filename_1, filename_2)
    time_decompress = decompress(flags, filename_2)

    return size_information + (time_compress, time_decompress)


def compress_decompress_explicit(file: str, extension: str, flags: dict):
    '''
    Compresses and decompresses the given file with the specified flags.
    This method should be used for algorithms, whose (de)compression command 
    expects explicit input and output file names as parameter.

    Example: 'snappy input.txt output.txt' will take input.txt and generate the
    compressed file output.txt. Decompression is analogous. This is referred to as
    explicit naming.
    
    Altough any naming can be used, this function follows the naming scheme of 
    implicit file names. Two new files will be generated with the names input.copy
    and input.copy.extension. The first one should be identical to the original input
    file, and the latter is the compressed data.
    '''
    filename_0 = file
    filename_1 = f'{file}.copy.{extension}'
    filename_2 = f'{file}.copy'

    time_compress = compress(flags, filename_0, filename_1)
    size_information = compare_file_sizes(filename_0, filename_1)
    time_decompress = decompress(flags, filename_1, filename_2)

    return size_information + (time_compress, time_decompress)




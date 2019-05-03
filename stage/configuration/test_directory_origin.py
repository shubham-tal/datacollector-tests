#
# -*- stage: com_streamsets_pipeline_stage_origin_spooldir_SpoolDirDSource -*-
#
# -*- start test template -*-
#     pipeline_builder = sdc_builder.get_pipeline_builder()
#     directory = pipeline_builder.add_stage('Directory')
#     directory.set_attributes({stage_attributes})
#     trash = pipeline_builder.add_stage('Trash')
#     directory >> trash
#
#     pipeline = pipeline_builder.build()
#     sdc_executor.add_pipeline(pipeline)
# -*- end test template -*-
#
import logging
import os
import math
import time

import pytest
from streamsets.sdk.sdc_api import StartError
from streamsets.testframework.markers import sdc_min_version
from streamsets.testframework.utils import get_random_string
from streamsets.testframework.markers import sdc_min_version

logger = logging.getLogger(__file__)


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('header_line', ['WITH_HEADER'])
@pytest.mark.parametrize('extra_columns_present', [False, True])
@pytest.mark.parametrize('allow_extra_columns', [False, True])
def test_directory_origin_configuration_allow_extra_columns(sdc_builder, sdc_executor,
                                                            shell_executor, file_writer,
                                                            data_format, header_line,
                                                            extra_columns_present, allow_extra_columns):
    """Test for Allow Extra Columns configuration covering the following scenarios:

    Extra Columns Present | Allow Extra Columns | Expected outcome
    --------------------------------------------------------------
    True                  | True                | File processed
    True                  | False               | Records to error
    False                 | True                | File processed
    False                 | False               | File processed
    """
    FILES_DIRECTORY = '/tmp'
    HEADER = ['columnA', 'columnB', 'columnC']
    EXTRA_COLUMNS_PRESENT_DATA = [dict(columnA='1', columnB='2', columnC='3'),
                                  dict(columnA='4', columnB='5', columnC='6', _extra_01='7'),
                                  dict(columnA='8', columnB='9', columnC='10', _extra_01='11', _extra_02='12')]
    EXTRA_COLUMNS_NOT_PRESENT_DATA = [dict(columnA='1', columnB='2', columnC='3'),
                                      dict(columnA='4', columnB='5', columnC='6'),
                                      dict(columnA='7', columnB='8', columnC='9')]
    file_name = f'{get_random_string()}.txt'
    file_path = os.path.join(FILES_DIRECTORY, file_name)

    try:
        data = EXTRA_COLUMNS_PRESENT_DATA if extra_columns_present else EXTRA_COLUMNS_NOT_PRESENT_DATA
        file_contents = '\n'.join([','.join(HEADER)] + [','.join(record.values()) for record in data])
        file_writer(file_path, file_contents)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(allow_extra_columns=allow_extra_columns,
                                 data_format=data_format,
                                 header_line=header_line,
                                 files_directory=FILES_DIRECTORY,
                                 file_name_pattern=file_name)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
        records = [record.field for record in snapshot[directory].output]
        error_records = [error_record.field['columns'] for error_record in snapshot[directory].error_records]
        sdc_executor.stop_pipeline(pipeline)
        if extra_columns_present and not allow_extra_columns:
            # The first record should show up in the snapshot, but the rest should go to error.
            assert records == data[0:1]
            assert error_records == [list(record.values()) for record in data[1:]]
        else:
            assert records == data
    finally:
        shell_executor(f'rm file_path')
        if sdc_executor.get_pipeline_status(pipeline).response.json().get('status') == 'RUNNING':
            sdc_executor.stop_pipeline(pipeline)


@pytest.mark.parametrize('create_directory_first', [True, False])
@pytest.mark.parametrize('allow_late_directory', [False, True])
def test_directory_origin_configuration_allow_late_directory(sdc_builder, sdc_executor,
                                                             shell_executor, file_writer,
                                                             create_directory_first, allow_late_directory):
    """Test for Allow Late Directory configuration covering the following scenarios:

    Create Directory Early | Allow Late Directory | Expected outcome
    ----------------------------------------------------------------
    True                   | True                 | File processed
    True                   | False                | File processed
    False                  | True                 | File processed
    False                  | False                | Error
    """

    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'keepingjoe.txt'
    FILE_CONTENTS = 'Sam is the Kid'

    def create_directory_and_file(files_directory, file_name, file_contents):
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, file_name), file_contents)

    try:
        if create_directory_first:
            create_directory_and_file(files_directory, FILE_NAME, FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(allow_late_directory=allow_late_directory,
                                 data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern=FILE_NAME)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        if not allow_late_directory and not create_directory_first:
            with pytest.raises(StartError):
                sdc_executor.start_pipeline(pipeline)
        else:
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            if not create_directory_first:
                assert not snapshot[directory].output
                create_directory_and_file(files_directory, FILE_NAME, FILE_CONTENTS)
                snapshot = sdc_executor.capture_snapshot(pipeline).snapshot

            record = snapshot[directory].output[0]
            assert record.field['text'] == FILE_CONTENTS
    finally:
        shell_executor(f'rm -r {files_directory}')
        if sdc_executor.get_pipeline_status(pipeline).response.json().get('status') == 'RUNNING':
            sdc_executor.stop_pipeline(pipeline)


@pytest.mark.parametrize('file_post_processing', ['ARCHIVE'])
def test_directory_origin_configuration_archive_directory(sdc_builder, sdc_executor,
                                                          shell_executor, file_writer,
                                                          file_post_processing):
    """Verify that the Archive Directory configuration is used when archiving files as part of post-processing."""
    files_directory = os.path.join('/tmp', get_random_string())
    archive_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'keepingjoe.txt'
    FILE_CONTENTS = "Machi's not the Kid"

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        logger.debug('Creating archive directory %s ...', archive_directory)
        shell_executor(f'mkdir {archive_directory}')

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(archive_directory=archive_directory,
                                 data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern=FILE_NAME,
                                 file_post_processing=file_post_processing)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
        record = snapshot[directory].output[0]
        assert record.field['text'] == FILE_CONTENTS
        sdc_executor.stop_pipeline(pipeline)
        # Confirm that the file has been archived by taking another snapshot and asserting to its emptiness.
        sdc_executor.reset_origin(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
        assert not snapshot[directory].output

        logger.info('Verifying that file %s was moved as part of post-processing ...', FILE_NAME)
        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=archive_directory,
                                 file_name_pattern=FILE_NAME)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
        record = snapshot[directory].output[0]
        assert record.field['text'] == FILE_CONTENTS

    finally:
        shell_executor(f'rm -r {files_directory} {archive_directory}')
        if sdc_executor.get_pipeline_status(pipeline).response.json().get('status') == 'RUNNING':
            sdc_executor.stop_pipeline(pipeline)


@pytest.mark.parametrize('file_post_processing', ['ARCHIVE'])
@pytest.mark.parametrize('wait_time_in_secs', [90, 1])
def test_directory_origin_configuration_archive_retention_time_in_mins(sdc_builder, sdc_executor, file_post_processing,
                                                                        shell_executor, file_writer, wait_time_in_secs):
    """Verify that the Archive retention in mins configuration is used when deleting archived files as part of post-processing.
        Here we will run file with file_post_processing=ARCHIVE and archive_retention_time_in_mins=1 configs.
        We check if file is present in archive. Then after waiting for 1.5 mins (90 secs) we check if the file in archived directory is deleted or not."""
    files_directory = os.path.join('/tmp', get_random_string())
    archive_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'archive_retention_test.txt'
    FILE_CONTENTS = "This is file contet to test archive retnetion."

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        logger.debug('Creating archive directory %s ...', archive_directory)
        shell_executor(f'mkdir {archive_directory}')

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(archive_directory=archive_directory,
                                 data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern=FILE_NAME,
                                 file_post_processing=file_post_processing,
                                 archive_retention_time_in_mins=1)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        sdc_executor.start_pipeline(pipeline).wait_for_pipeline_batch_count(1)
        time.sleep(wait_time_in_secs)
        sdc_executor.stop_pipeline(pipeline)

        if wait_time_in_secs < 60:
            logger.info('Verifying that file %s was moved as part of post-processing ...', FILE_NAME)
            pipeline_builder = sdc_builder.get_pipeline_builder()
            directory = pipeline_builder.add_stage('Directory')
            directory.set_attributes(data_format='TEXT',
                                     files_directory=archive_directory,
                                     file_name_pattern=FILE_NAME)
            trash = pipeline_builder.add_stage('Trash')
            directory >> trash
            pipeline = pipeline_builder.build()

            sdc_executor.add_pipeline(pipeline)
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            record = snapshot[directory].output[0]
            sdc_executor.stop_pipeline(pipeline)
            assert record.field['text'] == FILE_CONTENTS
        else:
            sdc_executor.reset_origin(pipeline)
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            assert not snapshot[directory].output
    finally:
        shell_executor(f'rm -r {files_directory} {archive_directory}')
        if sdc_executor.get_pipeline_status(pipeline).response.json().get('status') == 'RUNNING':
            sdc_executor.stop_pipeline(pipeline)


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['COLLECTD'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_auth_file(sdc_builder, sdc_executor, data_format, datagram_packet_format):
    pass


@pytest.mark.parametrize('data_format', ['AVRO'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_avro_schema(sdc_builder, sdc_executor, data_format):
    pass

@pytest.mark.parametrize('batch_size_in_recs', [2, 3, 4])
def test_directory_origin_configuration_batch_size_in_recs(sdc_builder, sdc_executor, shell_executor, file_writer, batch_size_in_recs):
    """
        Verify batch size in records (batch_size_in_recs) configuration for various values.
        e.g. For 2 files with each containing 3 records. Verify with batch_size_in_recs = 2 (less than records per file), 3 (equal to number of records per file), 4 (greater than number of records per file)
    """
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME1 = 'streamsets_temp1.txt'
    FILE_NAME2 = 'streamsets_temp2.txt'
    FILE_CONTENTS1 = """This is line11
This is line12
This is line13"""
    FILE_CONTENTS2 = """This is line21
This is line22
This is line23"""
    no_of_batches = math.ceil(6/batch_size_in_recs)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME1), FILE_CONTENTS1)
        file_writer(os.path.join(files_directory, FILE_NAME2), FILE_CONTENTS2)



        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern="*.txt",
                                 batch_size_in_recs=batch_size_in_recs)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=no_of_batches, batch_size=10).snapshot
        raw_data = FILE_CONTENTS1 + "\n" + FILE_CONTENTS2
        stage_output = ""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        stage_output +=  "\n" + rec if stage_output != "" else rec
        assert raw_data == stage_output
        sdc_executor.stop_pipeline(pipeline)
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_batch_wait_time_in_secs(sdc_builder, sdc_executor):
    pass


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_buffer_limit_in_kb(sdc_builder, sdc_executor):
    pass


@pytest.mark.parametrize('data_format', ['WHOLE_FILE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_buffer_size_in_bytes(sdc_builder, sdc_executor, data_format):
    pass


# TODO: Add test cases for other data formats.
@pytest.mark.parametrize('data_format', ['TEXT', # 'DATAGRAM', 'DELIMITED', 'JSON', 'LOG', 'XML'
                                        ])
@pytest.mark.parametrize('charset_correctly_set', [True, False])
def test_directory_origin_configuration_charset(sdc_builder, sdc_executor, file_writer,
                                                data_format, charset_correctly_set):
    """Instead of iterating over every possible charset (which would be a huge waste of time to write
    and run), let's just take some random set of characters from the Big5 character set and ensure that,
    if those characters are written to disk and the Directory charset is set correctly, that they're
    correctly parsed and they aren't if it isn't.
    """
    FILES_DIRECTORY = '/tmp'
    FILE_CONTENTS = '駿 鮮 鮫 鮪 鮭 鴻 鴿 麋 黏 點 黜 黝 黛 鼾 齋 叢'
    file_name = f'{get_random_string()}.txt'
    ENCODING = 'Big5'

    file_writer(os.path.join(FILES_DIRECTORY, file_name), FILE_CONTENTS, ENCODING)

    pipeline_builder = sdc_builder.get_pipeline_builder()
    directory = pipeline_builder.add_stage('Directory')
    directory.set_attributes(charset=ENCODING if charset_correctly_set else 'US-ASCII',
                             data_format=data_format,
                             files_directory=FILES_DIRECTORY,
                             file_name_pattern=file_name)
    trash = pipeline_builder.add_stage('Trash')
    directory >> trash
    pipeline = pipeline_builder.build('test_directory_origin_configuration_charset')

    sdc_executor.add_pipeline(pipeline)
    snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
    record = snapshot[directory].output[0]
    sdc_executor.stop_pipeline(pipeline)

    if charset_correctly_set:
        assert record.field['text'] == FILE_CONTENTS
    else:
        assert record.field['text'] != FILE_CONTENTS


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('enable_comments', [True])
@pytest.mark.parametrize('comment_marker', ['#'])
def test_directory_origin_configuration_comment_marker(sdc_builder, sdc_executor,
                                                       delimiter_format_type, data_format,
                                                       enable_comments, comment_marker, shell_executor, file_writer):
    """ Verify if DC can read the delimited file with comments"""
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'delimited_file.csv'
    FILE_CONTENTS = """Field11,Field12,Field13
{comment_marker} This is comment
Field21,Field22,Field23""".format(comment_marker=comment_marker)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="*.csv",
                                 file_name_pattern_mode='GLOB',
                                 delimiter_format_type=delimiter_format_type,
                                 enable_comments=enable_comments,
                                 comment_marker=comment_marker,
                                 delimiter_character=","
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        assert 2 == len(output_records)
        assert output_records[0].get_field_data('/0') == 'Field11'
        assert output_records[0].get_field_data('/1') == 'Field12'
        assert output_records[0].get_field_data('/2') == 'Field13'
        assert output_records[1].get_field_data('/0') == 'Field21'
        assert output_records[1].get_field_data('/1') == 'Field22'
        assert output_records[1].get_field_data('/2') == 'Field23'
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['BINARY', 'DELIMITED', 'JSON', 'LOG', 'PROTOBUF', 'SDC_JSON', 'TEXT', 'XML'])
@pytest.mark.parametrize('compression_format', ['ARCHIVE', 'COMPRESSED_ARCHIVE', 'COMPRESSED_FILE', 'NONE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_compression_format(sdc_builder, sdc_executor, data_format, compression_format):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['COLLECTD'])
@pytest.mark.parametrize('convert_hi_res_time_and_interval', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_convert_hi_res_time_and_interval(sdc_builder, sdc_executor,
                                                                         data_format, datagram_packet_format,
                                                                         convert_hi_res_time_and_interval):
    pass


@pytest.mark.parametrize('use_custom_delimiter', [True, False])
@pytest.mark.parametrize('data_format', ['DELIMITED']) #, 'TEXT'
@pytest.mark.parametrize('delimiter_character', ['^', '@'])
def test_directory_origin_configuration_custom_delimiter(sdc_builder, sdc_executor,
                                                         use_custom_delimiter, data_format,
                                                         delimiter_character, shell_executor, file_writer):
    """ Verify if DC can read the custom delimited file"""
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'delimited_file'
    FILE_CONTENTS = """Field11{delimiter_character}Field12{delimiter_character}Field13
Field21{delimiter_character}Field22{delimiter_character}Field23""".format(delimiter_character=delimiter_character)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="delimited_*",
                                 file_name_pattern_mode='GLOB',
                                 use_custom_delimiter=use_custom_delimiter,
                                 delimiter_character=delimiter_character,
                                 delimiter_format_type='CUSTOM'
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        assert 2 == len(output_records)
        if use_custom_delimiter:
            assert output_records[0].get_field_data('/0') == 'Field11'
            assert output_records[0].get_field_data('/1') == 'Field12'
            assert output_records[0].get_field_data('/2') == 'Field13'
            assert output_records[1].get_field_data('/0') == 'Field21'
            assert output_records[1].get_field_data('/1') == 'Field22'
            assert output_records[1].get_field_data('/2') == 'Field23'
        else:
            assert output_records[0].get_field_data('/0') != 'Field11'
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('use_custom_log_format', [True])
@pytest.mark.parametrize('log_format', ['LOG4J'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_custom_log4j_format(sdc_builder, sdc_executor,
                                                            data_format, use_custom_log_format, log_format):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['APACHE_CUSTOM_LOG_FORMAT'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_custom_log_format(sdc_builder, sdc_executor, data_format, log_format):
    pass


@pytest.mark.parametrize('data_format', ['AVRO', 'DELIMITED', 'EXCEL', 'JSON', 'LOG',
                                         'PROTOBUF', 'SDC_JSON', 'TEXT', 'WHOLE_FILE', 'XML'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_data_format(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['COLLECTD', 'NETFLOW', 'RAW_DATA', 'SYSLOG'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_datagram_packet_format(sdc_builder, sdc_executor,
                                                               data_format, datagram_packet_format):
    pass


@pytest.mark.parametrize('data_format', ['PROTOBUF'])
@pytest.mark.parametrize('delimited_messages', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_delimited_messages(sdc_builder, sdc_executor, data_format, delimited_messages):
    pass


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('delimiter_character', ['\t', ';', ',', ' '])
def test_directory_origin_configuration_delimiter_character(sdc_builder, sdc_executor,
                                                            delimiter_format_type, data_format,
							    delimiter_character, shell_executor, file_writer):
    """ Verify if DC can read the delimited file with custom delimiter character"""
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'custom_delimited_file.csv'
    FILE_CONTENTS = """Field11{delimiter_character}Field12{delimiter_character}Field13
Field21{delimiter_character}Field22{delimiter_character}Field23""".format(delimiter_character=delimiter_character)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="custom_delimited_*",
                                 file_name_pattern_mode='GLOB',
                                 delimiter_format_type=delimiter_format_type,
                                 delimiter_character=delimiter_character
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        assert 2 == len(output_records)
        assert output_records[0].get_field_data('/0') == 'Field11'
        assert output_records[0].get_field_data('/1') == 'Field12'
        assert output_records[0].get_field_data('/2') == 'Field13'
        assert output_records[1].get_field_data('/0') == 'Field21'
        assert output_records[1].get_field_data('/1') == 'Field22'
        assert output_records[1].get_field_data('/2') == 'Field23'

    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['XML'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_delimiter_element(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('delimiter_format_type', ['CSV', 'CUSTOM', 'EXCEL', 'MYSQL',
                                                   'POSTGRES_CSV', 'POSTGRES_TEXT', 'RFC4180', 'TDF'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_delimiter_format_type(sdc_builder, sdc_executor,
                                                              data_format, delimiter_format_type):
    pass


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('enable_comments', [False, True])
@pytest.mark.parametrize('comment_marker', ['#'])
def test_directory_origin_configuration_enable_comments(sdc_builder, sdc_executor,
                                                        shell_executor, file_writer, delimiter_format_type, data_format, enable_comments, 
                                                        comment_marker):
    """ Verify if DC can skip comments or read comments as texts"""    
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'delimited_file.csv'
    FILE_CONTENTS = """Field11,Field12,Field13
{comment_marker} This is comment
Field21,Field22,Field23""".format(comment_marker=comment_marker)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="*.csv",
                                 file_name_pattern_mode='GLOB',
                                 delimiter_format_type=delimiter_format_type,
                                 enable_comments=enable_comments,
                                 comment_marker=comment_marker,
                                 delimiter_character=","
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        if enable_comments :
            assert 2 == len(output_records)
            assert output_records[0].get_field_data('/0') == 'Field11'
            assert output_records[0].get_field_data('/1') == 'Field12'
            assert output_records[0].get_field_data('/2') == 'Field13'
            assert output_records[1].get_field_data('/0') == 'Field21'
            assert output_records[1].get_field_data('/1') == 'Field22'
            assert output_records[1].get_field_data('/2') == 'Field23'
        else :
            assert 3 == len(output_records)
            assert output_records[0].get_field_data('/0') == 'Field11'
            assert output_records[0].get_field_data('/1') == 'Field12'
            assert output_records[0].get_field_data('/2') == 'Field13'
            assert output_records[1].get_field_data('/0') == '# This is comment'
            assert output_records[2].get_field_data('/0') == 'Field21'
            assert output_records[2].get_field_data('/1') == 'Field22'
            assert output_records[2].get_field_data('/2') == 'Field23'
    finally:
        shell_executor(f'rm -r {files_directory}')


def test_directory_origin_configuration_error_directory(sdc_builder, sdc_executor,
                                                        shell_executor, file_writer):
    """Check if the error directory configuration works properly. Here we create
        text file and make directory origin read it as XML file to produce error.
        Initially error direcotry is empty. Error in processing should move file to error direcotry.
        Then we process error directory and check its content"""
    files_directory = os.path.join('/tmp', get_random_string())
    error_directory = os.path.join('/tmp', 'error_' + get_random_string())
    file_name = 'check_error_dir.txt'
    file_content = ["This is line 1", "This is line 2"]

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, file_name), "\n".join(file_content))

        logger.debug('Creating error directory %s ...', error_directory)
        shell_executor(f'mkdir {error_directory}')

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format="XML",
                                 files_directory=files_directory,
                                 error_directory=error_directory,
                                 file_name_pattern_mode='GLOB',
                                 buffer_size_in_bytes=1,
                                 file_name_pattern='*.txt')
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_error_directory')

        sdc_executor.add_pipeline(pipeline)
        sdc_executor.start_pipeline(pipeline).wait_for_pipeline_batch_count(1)
        sdc_executor.stop_pipeline(pipeline)

        ## Check the error directory output
        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=error_directory,
                                 file_name_pattern_mode='GLOB',
                                 file_name_pattern='*.*')
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_error_directory_op')
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=1, batch_size=10).snapshot
        record = snapshot[directory].output[0]
        sdc_executor.stop_pipeline(pipeline)
        print ("record :: " + str(record.field['text']))
        assert record.field['text'] == file_content[0]
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('escape_character', ['\t', ';' , ' '])
def test_directory_origin_configuration_escape_character(sdc_builder, sdc_executor, delimiter_format_type, data_format,
							 escape_character, shell_executor, file_writer):
    """ Verify if DC can read the delimited file with custom escape character"""
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'custom_delimited_file.csv'
    FILE_CONTENTS = """Field11{escape_character},,Field12,{escape_character},Field13
Field{escape_character},21,Field22,Field23""".format(escape_character=escape_character)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="custom_delimited_*",
                                 file_name_pattern_mode='GLOB',
                                 delimiter_format_type=delimiter_format_type,
                                 delimiter_character=",",
				 escape_character=escape_character
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        assert 2 == len(output_records)
        assert output_records[0].get_field_data('/0') == 'Field11,'
        assert output_records[0].get_field_data('/1') == 'Field12'
        assert output_records[0].get_field_data('/2') == ',Field13'
        assert output_records[1].get_field_data('/0') == 'Field,21'
        assert output_records[1].get_field_data('/1') == 'Field22'
        assert output_records[1].get_field_data('/2') == 'Field23'

    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['EXCEL'])
@pytest.mark.parametrize('excel_header_option', ['IGNORE_HEADER', 'NO_HEADER', 'WITH_HEADER'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_excel_header_option(sdc_builder, sdc_executor,
                                                            data_format, excel_header_option):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['COLLECTD'])
@pytest.mark.parametrize('exclude_interval', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_exclude_interval(sdc_builder, sdc_executor,
                                                         data_format, datagram_packet_format, exclude_interval):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('allow_extra_columns', [True])
@pytest.mark.parametrize('header_line', ['WITH_HEADER'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_extra_column_prefix(sdc_builder, sdc_executor,
                                                            data_format, allow_extra_columns, header_line):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['REGEX'])
def test_directory_origin_configuration_field_path_to_regex_group_mapping(sdc_builder, sdc_executor, data_format,
                                                                          log_format, shell_executor, file_writer):
    """Check if the file regex group mapping for the log format works properly. Here we consider logs from DC as our test data.
        We provide the DC with regex that groups data in date, time, timehalf, info, file and message fields."""
    files_directory = os.path.join('/tmp', get_random_string())
    file_name = 'custom_log_data.log'
    file_content = """2019-04-30 08:23:53 AM [INFO] [streamsets.sdk.sdc_api] Pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 reached status EDITED (took 0.00 s).
2019-04-30 08:23:57 AM [INFO] [streamsets.sdk.sdc] Starting pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 ...
2019-04-30 08:23:59 AM [INFO] [streamsets.sdk.sdc_api] Waiting for status ['RUNNING', 'FINISHED'] ..."""

    field_path_to_regex_group_mapping = [{"fieldPath": "/date","group": 1 },
                                         {"fieldPath": "/time","group": 2},
                                         {"fieldPath": "/timehalf", "group": 3},
                                         {"fieldPath": "/info", "group": 4},
                                         {"fieldPath": "/file", "group": 5},
                                         {"fieldPath": "/message", "group": 6}]

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, file_name), file_content)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 log_format=log_format,
                                 files_directory=files_directory,
                                 file_name_pattern_mode='GLOB',
                                 file_name_pattern='*.log',
                                 field_path_to_regex_group_mapping=field_path_to_regex_group_mapping,
                                 regular_expression="(\S+) (\S+) (\S+) (\S+) (\S+) (.*)"
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_field_path_to_regex_group_mapping')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=1, batch_size=10).snapshot
        output_records = snapshot[directory].output
        sdc_executor.stop_pipeline(pipeline)
        assert output_records[0].field['/date'] == '2019-04-30'
        assert output_records[0].field['/time'] == '08:23:53'
        assert output_records[0].field['/file'] == '[streamsets.sdk.sdc_api]'
        assert output_records[0].field['/message'] == 'Pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 reached status EDITED (took 0.00 s).'
        assert output_records[1].field['/date'] == '2019-04-30'
        assert output_records[1].field['/time'] == '08:23:57'
        assert output_records[1].field['/file'] == '[streamsets.sdk.sdc]'
        assert output_records[1].field[ '/message'] == 'Starting pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 ...'
        assert output_records[2].field['/date'] == '2019-04-30'
        assert output_records[2].field['/time'] == '08:23:59'
        assert output_records[2].field['/file'] == '[streamsets.sdk.sdc_api]'
        assert output_records[2].field['/message'] == 'Waiting for status [\'RUNNING\', \'FINISHED\'] ...'
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('file_name_pattern', ['pattern_check_processing_1.txt', '*.txt', 'pattern_*', '*_check_*'])
@sdc_min_version('3.4.1')
def test_directory_origin_configuration_file_name_pattern(sdc_builder, sdc_executor, shell_executor,
                                                          file_writer, file_name_pattern):
    """Check how DC process different forms of the file name patterns. """
    files_directory = os.path.join('/tmp', get_random_string())
    files_name = ['pattern_check_processing_1.txt', 'pattern_check_processing_2.txt']
    files_content = ["This is sample file111", "This is sample file222"]

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, files_name[0]), files_content[0])
        file_writer(os.path.join(files_directory, files_name[1]), files_content[1])

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                file_name_pattern=file_name_pattern,
                                file_name_pattern_mode='GLOB',
                                files_directory=files_directory,
                                )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_file_name_pattern')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=2, batch_size=10).snapshot
        raw_data = "\n".join(files_content)
        processed_data=""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        processed_data +=  "\n" + rec if processed_data != "" else rec

        sdc_executor.stop_pipeline(pipeline)
        if file_name_pattern == 'pattern_check_processing_1.txt':
            assert files_content[0] == processed_data
        else:
            assert raw_data == processed_data
    finally:
        shell_executor(f'rm -r {files_directory}')



@pytest.mark.parametrize('file_name_pattern_mode', ['GLOB', 'REGEX'])
def test_directory_origin_configuration_file_name_pattern_mode(sdc_builder, sdc_executor, shell_executor,
                                                               file_writer, file_name_pattern_mode):
    """Check how DC process different file pattern mode. Here we will be creating 2 files.
        pattern_check_processing_1.txt and pattern_check_processing_22.txt.
        with regex we match only 1st file and with glob both files. """
    files_directory = os.path.join('/tmp', get_random_string())
    files_name = ['pattern_check_processing_1.txt', 'pattern_check_processing_22.txt']
    files_content = ["This is sample file111", "This is sample file222"]
    file_name_pattern = "*.txt" if file_name_pattern_mode == "GLOB" else "^p(.*)([0-9]{1})(\.txt)"
    no_of_batches = 2 if file_name_pattern_mode == "GLOB" else 1

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, files_name[0]), files_content[0])
        file_writer(os.path.join(files_directory, files_name[1]), files_content[1])

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern_mode=file_name_pattern_mode,
                                 file_name_pattern=file_name_pattern)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_file_name_pattern_mode')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=no_of_batches, batch_size=10).snapshot
        raw_data = "\n".join(files_content)
        processed_data = ""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        processed_data += "\n" + rec if processed_data != "" else rec

        sdc_executor.stop_pipeline(pipeline)
        if file_name_pattern_mode == "GLOB":
            assert raw_data == processed_data
        else:
            assert files_content[0] == processed_data
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['BINARY', 'DELIMITED', 'JSON', 'LOG', 'PROTOBUF', 'SDC_JSON', 'TEXT', 'XML'])
@pytest.mark.parametrize('compression_format', ['ARCHIVE', 'COMPRESSED_ARCHIVE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_file_name_pattern_within_compressed_directory(sdc_builder, sdc_executor,
                                                                                      data_format, compression_format):
    pass


@pytest.mark.parametrize('file_post_processing', ['ARCHIVE', 'DELETE', 'NONE'])
@sdc_min_version('3.4.1')
def test_directory_origin_configuration_file_post_processing(sdc_builder, sdc_executor, file_post_processing, shell_executor, file_writer):
    """Verify that the File post processing configuration is used as part of post-processing activities archive, delete and no operaration."""
    files_directory = os.path.join('/tmp', get_random_string())
    archive_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'streamsets_test.txt'
    FILE_CONTENTS = "File content for testing purpose."

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        logger.debug('Creating archive directory %s ...', archive_directory)
        shell_executor(f'mkdir {archive_directory}')

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(archive_directory=archive_directory,
                                 data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern=FILE_NAME,
                                 file_post_processing=file_post_processing)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
        record = snapshot[directory].output[0]
        assert record.field['text'] == FILE_CONTENTS
        sdc_executor.stop_pipeline(pipeline)

        if file_post_processing == 'NONE':
            #Check if the file is in tact by rerunning the pipeline
            sdc_executor.reset_origin(pipeline)
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            record = snapshot[directory].output[0]
            assert record.field['text'] == FILE_CONTENTS
            sdc_executor.stop_pipeline(pipeline)
        elif file_post_processing in ['ARCHIVE', 'DELETE']:
            # Confirm that the file has been archived by taking another snapshot and asserting to its emptiness.
            sdc_executor.reset_origin(pipeline)
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            assert not snapshot[directory].output

        if file_post_processing == 'ARCHIVE':
            logger.info('Verifying that file %s was moved as part of post-processing ...', FILE_NAME)
            pipeline_builder = sdc_builder.get_pipeline_builder()
            directory = pipeline_builder.add_stage('Directory')
            directory.set_attributes(data_format='TEXT',
                                     files_directory=archive_directory,
                                     file_name_pattern=FILE_NAME)
            trash = pipeline_builder.add_stage('Trash')
            directory >> trash
            pipeline = pipeline_builder.build()

            sdc_executor.add_pipeline(pipeline)
            snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True).snapshot
            record = snapshot[directory].output[0]
            assert record.field['text'] == FILE_CONTENTS
    finally:
        shell_executor(f'rm -r {files_directory} {archive_directory}')
        if sdc_executor.get_pipeline_status(pipeline).response.json().get('status') == 'RUNNING':
            sdc_executor.stop_pipeline(pipeline)


def test_directory_origin_configuration_files_directory(sdc_builder, sdc_executor, shell_executor,
                                                        file_writer):
    """Check if the file directory configuration works properly """
    files_directory = os.path.join('/tmp', get_random_string())
    files_name = ['pattern_check_processing_1.txt', 'pattern_check_processing_22.txt']
    files_content = ["This is sample file111", "This is sample file222"]

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, files_name[0]), files_content[0])
        file_writer(os.path.join(files_directory, files_name[1]), files_content[1])

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern_mode='GLOB',
                                 file_name_pattern='*.txt')
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_files_directory')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=2, batch_size=10).snapshot
        raw_data = "\n".join(files_content)
        processed_data = ""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        processed_data += "\n" + rec if processed_data != "" else rec

        sdc_executor.stop_pipeline(pipeline)
        assert raw_data == processed_data
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_first_file_to_process(sdc_builder, sdc_executor):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['GROK'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_grok_pattern(sdc_builder, sdc_executor, data_format, log_format):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['GROK'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_grok_pattern_definition(sdc_builder, sdc_executor, data_format, log_format):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('header_line', ['IGNORE_HEADER', 'NO_HEADER', 'WITH_HEADER'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_header_line(sdc_builder, sdc_executor, data_format, header_line):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM', 'DELIMITED', 'JSON', 'LOG', 'TEXT', 'XML'])
@pytest.mark.parametrize('ignore_control_characters', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_ignore_control_characters(sdc_builder, sdc_executor,
                                                                  data_format, ignore_control_characters):
    pass


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('ignore_empty_lines', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_ignore_empty_lines(sdc_builder, sdc_executor,
                                                           delimiter_format_type, data_format, ignore_empty_lines):
    pass


@pytest.mark.parametrize('use_custom_delimiter', [True])
@pytest.mark.parametrize('data_format', ['TEXT'])
@pytest.mark.parametrize('include_custom_delimiter', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_include_custom_delimiter(sdc_builder, sdc_executor,
                                                                 use_custom_delimiter, data_format,
                                                                 include_custom_delimiter):
    pass


@pytest.mark.parametrize('data_format', ['XML'])
@pytest.mark.parametrize('include_field_xpaths', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_include_field_xpaths(sdc_builder, sdc_executor,
                                                             data_format, include_field_xpaths):
    pass


@pytest.mark.parametrize('data_format', ['JSON'])
@pytest.mark.parametrize('json_content', ['ARRAY_OBJECTS', 'MULTIPLE_OBJECTS'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_json_content(sdc_builder, sdc_executor, data_format, json_content):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_lines_to_skip(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['APACHE_CUSTOM_LOG_FORMAT', 'APACHE_ERROR_LOG_FORMAT', 'CEF',
                                        'COMBINED_LOG_FORMAT', 'COMMON_LOG_FORMAT', 'GROK', 'LEEF', 'LOG4J', 'REGEX'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_log_format(sdc_builder, sdc_executor, data_format, log_format):
    pass


@pytest.mark.parametrize('data_format', ['AVRO'])
@pytest.mark.parametrize('lookup_schema_by', ['AUTO', 'ID', 'SUBJECT'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_lookup_schema_by(sdc_builder, sdc_executor, data_format, lookup_schema_by):
    pass


@pytest.mark.parametrize('data_format', ['BINARY'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_data_size_in_bytes(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_files_soft_limit(sdc_builder, sdc_executor):
    pass


@pytest.mark.parametrize('data_format', ['TEXT'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_line_length(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_line_length(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['JSON'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_object_length_in_chars(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_record_length_in_chars(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['XML'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_record_length_in_chars(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['NETFLOW'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_templates_in_cache(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['NETFLOW'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_max_templates_in_cache(sdc_builder, sdc_executor,
                                                               data_format, datagram_packet_format):
    pass


@pytest.mark.parametrize('data_format', ['PROTOBUF'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_message_type(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['XML'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_namespaces(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('parse_nulls', [True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_null_constant(sdc_builder, sdc_executor, data_format, parse_nulls):
    pass


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_number_of_threads(sdc_builder, sdc_executor):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['LOG4J'])
@pytest.mark.parametrize('on_parse_error', ['ERROR', 'IGNORE', 'INCLUDE_AS_STACK_TRACE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_on_parse_error(sdc_builder, sdc_executor,
                                                       data_format, log_format, on_parse_error):
    pass


@pytest.mark.parametrize('on_record_error', ['DISCARD', 'STOP_PIPELINE', 'TO_ERROR'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_on_record_error(sdc_builder, sdc_executor, on_record_error):
    pass


@pytest.mark.parametrize('data_format', ['XML'])
@pytest.mark.parametrize('output_field_attributes', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_output_field_attributes(sdc_builder, sdc_executor,
                                                                data_format, output_field_attributes):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('parse_nulls', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_parse_nulls(sdc_builder, sdc_executor, data_format, parse_nulls):
    pass


@pytest.mark.parametrize('read_order', ['TIMESTAMP'])
@pytest.mark.parametrize('process_subdirectories', [False, True])
def test_directory_origin_configuration_process_subdirectories(sdc_builder, sdc_executor,
                                                               read_order, process_subdirectories, shell_executor, file_writer):
    """Check if the process_subdirectories configuration works properly. Here we will create  two files one
        in root level (direcotry which we process) and one in nested directory"""
    files_directory = os.path.join('/tmp', get_random_string())
    inner_direcotry = os.path.join(files_directory, get_random_string())
    files_name = ['pattern_check_processing_1.txt', 'pattern_check_processing_2.txt']
    files_content = ["This is sample file111", "This is sample file222"]
    no_of_batches = 2 if process_subdirectories else 1

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        logger.debug('Creating nested direcotry within files directory %s ...', files_directory)
        shell_executor(f'mkdir {inner_direcotry}')
        file_writer(os.path.join(files_directory, files_name[0]), files_content[0])
        file_writer(os.path.join(inner_direcotry, files_name[1]), files_content[1])

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=files_directory,
                                 process_subdirectories=process_subdirectories,
                                 read_order=read_order,
                                 file_name_pattern_mode='GLOB',
                                 file_name_pattern='*.txt')
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_process_subdirectories')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=no_of_batches, batch_size=10).snapshot
        raw_data = "\n".join(files_content) if process_subdirectories else files_content[0]
        processed_data = ""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        processed_data += "\n" + rec if processed_data != "" else rec

        sdc_executor.stop_pipeline(pipeline)
        assert raw_data == processed_data
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['PROTOBUF'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_protobuf_descriptor_file(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('delimiter_format_type', ['CUSTOM'])
@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('quote_character', ['\t', ';' , ' '])
def test_directory_origin_configuration_quote_character(sdc_builder, sdc_executor, delimiter_format_type, data_format,
							 quote_character, shell_executor, file_writer):
    """ Verify if DC can read the delimited file with custom quote character"""
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME = 'custom_delimited_file.csv'
    FILE_CONTENTS = """{quote_character}Field11,{quote_character},Field12,{quote_character},Field13{quote_character}
{quote_character}Field,21{quote_character},Field22,Field23""".format(quote_character=quote_character)

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME), FILE_CONTENTS)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 files_directory=files_directory,
                                 file_name_pattern="custom_delimited_*",
                                 file_name_pattern_mode='GLOB',
                                 delimiter_format_type=delimiter_format_type,
                                 delimiter_character=",",
				  quote_character=quote_character
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build()
        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batch_size=3).snapshot
        sdc_executor.stop_pipeline(pipeline)
        output_records = snapshot[directory.instance_name].output

        assert 2 == len(output_records)
        assert output_records[0].get_field_data('/0') == 'Field11,'
        assert output_records[0].get_field_data('/1') == 'Field12'
        assert output_records[0].get_field_data('/2') == ',Field13'
        assert output_records[1].get_field_data('/0') == 'Field,21'
        assert output_records[1].get_field_data('/1') == 'Field22'
        assert output_records[1].get_field_data('/2') == 'Field23'

    finally:
        shell_executor(f'rm -r {files_directory}')



@pytest.mark.parametrize('data_format', ['WHOLE_FILE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_rate_per_second(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('read_order', ['LEXICOGRAPHICAL', 'TIMESTAMP'])
def test_directory_origin_configuration_read_order(sdc_builder, sdc_executor, shell_executor,
                                                   file_writer, read_order):
    """Check how DC process different file pattern mode. Here we will be creating 2 files.
            pattern_check_processing_0.txt and pattern_check_processing_01.txt.
            with regex we match only 1st file and with glob both files. """
    files_directory = os.path.join('/tmp', get_random_string())
    FILE_NAME1= 'b_read_order_check.txt'
    FILE_CONTENTS1 = "This is B file content"
    FILE_NAME2 = 'a_read_order_check.txt'
    FILE_CONTENTS2 = "This is A file content"

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, FILE_NAME1), FILE_CONTENTS1)
        time.sleep(5)
        file_writer(os.path.join(files_directory, FILE_NAME2), FILE_CONTENTS2)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format='TEXT',
                                 files_directory=files_directory,
                                 file_name_pattern_mode="GLOB",
                                 file_name_pattern="*.txt",
                                 read_order=read_order)
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_read_order')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=2, batch_size=10).snapshot
        processed_data = ""
        for snapshot_batch in snapshot.snapshot_batches:
            for value in snapshot_batch[directory.instance_name].output_lanes.values():
                for record in value:
                    if 'text' in record.value['value']:
                        rec = record.value['value']['text']['value']
                        processed_data += "\n" + rec if processed_data != "" else rec

        sdc_executor.stop_pipeline(pipeline)
        if read_order == "LEXICOGRAPHICAL":
            raw_data = FILE_CONTENTS2 + "\n" + FILE_CONTENTS1
        else:
            raw_data = FILE_CONTENTS1 + "\n" + FILE_CONTENTS2
        assert raw_data == processed_data
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['NETFLOW'])
@pytest.mark.parametrize('record_generation_mode', ['INTERPRETED_ONLY', 'RAW_AND_INTERPRETED', 'RAW_ONLY'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_record_generation_mode(sdc_builder, sdc_executor,
                                                               data_format, record_generation_mode):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['NETFLOW'])
@pytest.mark.parametrize('record_generation_mode', ['INTERPRETED_ONLY', 'RAW_AND_INTERPRETED', 'RAW_ONLY'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_record_generation_mode(sdc_builder, sdc_executor,
                                                               data_format, datagram_packet_format,
                                                               record_generation_mode):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['REGEX'])
@pytest.mark.parametrize('regular_expression', ["(\S+) (\S+) (\S+) (\S+) (\S+) (.*)", "(\S+)(\W+)(\S+)\[(\W+)\](\S+)(\W+)"])
@sdc_min_version('3.4.1')
def test_directory_origin_configuration_regular_expression(sdc_builder, sdc_executor, data_format,
                                                           log_format, shell_executor, file_writer, regular_expression):
    """Check if the regular expression configuration works. Here we consider logs from DC as our test data.
        There are two interations of this test case. One with valid regex which should parse logs. Another with invalid regex
        which should produce null or no result. """
    files_directory = os.path.join('/tmp', get_random_string())
    file_name = 'custom_log_data.log'
    file_content = """2019-04-30 08:23:53 AM [INFO] [streamsets.sdk.sdc_api] Pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 reached status EDITED (took 0.00 s).
    2019-04-30 08:23:57 AM [INFO] [streamsets.sdk.sdc] Starting pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 ..."""

    field_path_to_regex_group_mapping = [{"fieldPath": "/date", "group": 1},
                                         {"fieldPath": "/time", "group": 2},
                                         {"fieldPath": "/timehalf", "group": 3},
                                         {"fieldPath": "/info", "group": 4},
                                         {"fieldPath": "/file", "group": 5},
                                         {"fieldPath": "/message", "group": 6}]

    try:
        logger.debug('Creating files directory %s ...', files_directory)
        shell_executor(f'mkdir {files_directory}')
        file_writer(os.path.join(files_directory, file_name), file_content)

        pipeline_builder = sdc_builder.get_pipeline_builder()
        directory = pipeline_builder.add_stage('Directory')
        directory.set_attributes(data_format=data_format,
                                 log_format=log_format,
                                 files_directory=files_directory,
                                 file_name_pattern_mode='GLOB',
                                 file_name_pattern='*.log',
                                 field_path_to_regex_group_mapping=field_path_to_regex_group_mapping,
                                 regular_expression=regular_expression
                                 )
        trash = pipeline_builder.add_stage('Trash')
        directory >> trash
        pipeline = pipeline_builder.build('test_directory_origin_configuration_regular_expression')

        sdc_executor.add_pipeline(pipeline)
        snapshot = sdc_executor.capture_snapshot(pipeline, start_pipeline=True, batches=1, batch_size=10).snapshot
        output_records = snapshot[directory].output
        sdc_executor.stop_pipeline(pipeline)
        if regular_expression == "(\S+)(\W+)(\S+)\[(\W+)\](\S+)(\W+)":
            assert not output_records
        else:
            assert output_records[0].field['/date'] == '2019-04-30'
            assert output_records[0].field['/time'] == '08:23:53'
            assert output_records[0].field['/file'] == '[streamsets.sdk.sdc_api]'
            assert output_records[0].field['/message'] == 'Pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 reached status EDITED (took 0.00 s).'
            assert output_records[1].field['/date'] == '2019-04-30'
            assert output_records[1].field['/time'] == '08:23:57'
            assert output_records[1].field['/file'] == '[streamsets.sdk.sdc]'
            assert output_records[1].field['/message'] == 'Starting pipeline Filewriterpipeline5340a2b5-b792-45f7-ac44-cf3d6df1dc29 ...'
    finally:
        shell_executor(f'rm -r {files_directory}')


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('retain_original_line', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_retain_original_line(sdc_builder, sdc_executor,
                                                             data_format, retain_original_line):
    pass


@pytest.mark.parametrize('data_format', ['DELIMITED'])
@pytest.mark.parametrize('root_field_type', ['LIST', 'LIST_MAP'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_root_field_type(sdc_builder, sdc_executor, data_format, root_field_type):
    pass


@pytest.mark.parametrize('data_format', ['AVRO'])
@pytest.mark.parametrize('lookup_schema_by', ['ID'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_schema_id(sdc_builder, sdc_executor, data_format, lookup_schema_by):
    pass


@pytest.mark.parametrize('data_format', ['AVRO'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_schema_registry_urls(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['AVRO'])
@pytest.mark.parametrize('lookup_schema_by', ['SUBJECT'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_schema_subject(sdc_builder, sdc_executor, data_format, lookup_schema_by):
    pass


@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_spooling_period_in_secs(sdc_builder, sdc_executor):
    pass


@pytest.mark.parametrize('data_format', ['NETFLOW'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_template_cache_timeout_in_ms(sdc_builder, sdc_executor, data_format):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['NETFLOW'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_template_cache_timeout_in_ms(sdc_builder, sdc_executor,
                                                                     data_format, datagram_packet_format):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['LOG4J'])
@pytest.mark.parametrize('on_parse_error', ['INCLUDE_AS_STACK_TRACE'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_trim_stack_trace_to_length(sdc_builder, sdc_executor,
                                                                   data_format, log_format, on_parse_error):
    pass


@pytest.mark.parametrize('data_format', ['DATAGRAM'])
@pytest.mark.parametrize('datagram_packet_format', ['COLLECTD'])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_typesdb_file_path(sdc_builder, sdc_executor,
                                                          data_format, datagram_packet_format):
    pass


@pytest.mark.parametrize('data_format', ['TEXT'])
@pytest.mark.parametrize('use_custom_delimiter', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_use_custom_delimiter(sdc_builder, sdc_executor,
                                                             data_format, use_custom_delimiter):
    pass


@pytest.mark.parametrize('data_format', ['LOG'])
@pytest.mark.parametrize('log_format', ['LOG4J'])
@pytest.mark.parametrize('use_custom_log_format', [False, True])
@pytest.mark.skip('Not yet implemented')
def test_directory_origin_configuration_use_custom_log_format(sdc_builder, sdc_executor,
                                                              data_format, log_format, use_custom_log_format):
    pass

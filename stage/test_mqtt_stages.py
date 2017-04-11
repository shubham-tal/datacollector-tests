import logging
import time

import pytest

from testframework import environment, sdc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.fixture(scope='module')
def mqtt_inst(args):
    return environment.MQTT()

def do_mqtt_sanity_check(mqtt_inst, topic):
    """
    perform mqtt sanity check to ensure broker is functioning (publish a message and consume it)
    """

    sanity_check_msg = b'sanity check from Python'
    mqtt_inst.publish_message(topic=topic, payload=sanity_check_msg, qos=2)
    sanity_check_msgs = mqtt_inst.get_messages(num=1)
    assert len(sanity_check_msgs) == 1
    assert sanity_check_msgs[0].payload == sanity_check_msg
    assert sanity_check_msgs[0].topic == topic

def test_raw_to_mqtt(args, mqtt_inst):
    # pylint: disable=too-many-locals
    """
    Integration test for the MQTT destination stage.

     1) load a pipeline that has a raw data (text) origin and MQTT destination
     2) create MQTT instance (broker and a subscribed client) and inject appropriate values into
        the pipeline config
     3) run the pipeline and capture a snapshot
     4) check messages received by the MQTT client and ensure their number and contents match the
        pipeline origin data
    """

    sanity_check_topic = 'SANITY_CHECK'
    data_topic = 'testframework_mqtt_topic'

    try:
        mqtt_inst.initialize(initial_topics=[data_topic, sanity_check_topic])

        do_mqtt_sanity_check(mqtt_inst, sanity_check_topic)

        with sdc.DataCollector() as data_collector:
            data_collector.start()
            pipeline_builder = data_collector.get_pipeline_builder()

            raw_str = 'dummy_value'
            dev_raw_data_source = pipeline_builder.add_stage('Dev Raw Data Source')
            dev_raw_data_source.data_format = 'TEXT'
            dev_raw_data_source.raw_data = raw_str
            mqtt_target = pipeline_builder.add_stage('MQTT Publisher')
            host = mqtt_inst.broker_host
            port = mqtt_inst.broker_port
            mqtt_target.configuration['commonConf.brokerUrl'] = 'tcp://{0}:{1}'.format(host, port)
            mqtt_target.configuration['publisherConf.topic'] = data_topic
            mqtt_target.configuration['publisherConf.dataFormat'] = 'TEXT'
            discard = pipeline_builder.add_error_stage('Discard')

            dev_raw_data_source > mqtt_target

            pipeline = pipeline_builder.build()

            data_collector.add_pipeline(pipeline)
            snapshot = data_collector.capture_snapshot(pipeline, start_pipeline=True).wait_for_finished().snapshot
            data_collector.stop_pipeline(pipeline).wait_for_stopped()

            output_records = snapshot[dev_raw_data_source.instance_name].output
            for output_record in output_records:
                # sanity checks on output of raw data source
                assert output_record.value['value']['text']['value'] == raw_str

            # with QOS=2 (default), exactly one message should be received per published message
            # so we should have no trouble getting as many messages as output records from the
            # snapshot
            pipeline_msgs = mqtt_inst.get_messages(num=len(output_records))
            for msg in pipeline_msgs:
                assert msg.payload.decode().rstrip() == raw_str
                assert msg.topic == data_topic
    finally:
        mqtt_inst.destroy()

def test_mqtt_to_trash(args, mqtt_inst):
    # pylint: disable=too-many-locals
    """
    Integration test for the MQTT origin stage.

     1) load a pipeline that has an MQTT origin (text format) to trash
     2) create MQTT instance (broker and a subscribed client) and inject appropriate values into
        the pipeline config
     3) run the pipeline and capture a snapshot
     4) (in parallel) send message to the topic the pipeline is subscribed to
     5) after snapshot completes, verify outputs from pipeline snapshot against published messages
    """

    sanity_check_topic = 'SANITY_CHECK'
    data_topic = 'mqtt_subscriber_topic'
    try:
        host = mqtt_inst.broker_host
        port = mqtt_inst.broker_port
        mqtt_inst.initialize(initial_topics=[data_topic, sanity_check_topic])

        do_mqtt_sanity_check(mqtt_inst, sanity_check_topic)

        with sdc.DataCollector() as data_collector:
            data_collector.start()

            pipeline_builder = data_collector.get_pipeline_builder()

            mqtt_source = pipeline_builder.add_stage('MQTT Subscriber')
            discard = pipeline_builder.add_error_stage('Discard')
            cnf = mqtt_source.configuration
            cnf['subscriberConf.dataFormat'] = 'TEXT'
            cnf['commonConf.brokerUrl'] = 'tcp://{0}:{1}'.format(host, port)
            cnf['subscriberConf.topicFilters'] = [data_topic]

            trash = pipeline_builder.add_stage('Trash')
            mqtt_source > trash

            pipeline = pipeline_builder.build()
            data_collector.add_pipeline(pipeline)
            # the MQTT origin produces a single batch for each message it receieves, so we need
            # to run a separate snapshot for each message to be received
            running_snapshot = data_collector.capture_snapshot(pipeline, start_pipeline=True,
                                                               batches=10)

            # can't figure out a cleaner way to do this; it takes a bit of time for the pipeline
            # to ACTUALLY start listening on the MQTT port, so if we don't sleep here, the
            # messages won't be delivered (without setting persist)
            time.sleep(1)
            expected_messages = set()
            for i in range(10):
                expected_message = 'Message {0}'.format(i)
                mqtt_inst.publish_message(topic=data_topic, payload=expected_message)
                expected_messages.add(expected_message)

            snapshot = running_snapshot.wait_for_finished().snapshot
            data_collector.stop_pipeline(pipeline).wait_for_stopped()

            for batch in snapshot.snapshot_batches:
                output_records = batch[mqtt_source.instance_name].output
                # each batch should only contain one record
                assert len(output_records) == 1

                for output_record in output_records:
                    value = output_record.value['value']['text']['value']
                    assert value in expected_messages
                    assert expected_messages.remove(value) is None
            assert len(expected_messages) == 0


    finally:
        mqtt_inst.destroy()
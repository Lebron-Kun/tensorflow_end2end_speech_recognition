#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""Multi-task unidirectional LSTM encoder."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf


class Multitask_LSTM_Encoder(object):
    """Multi-task unidirectional LSTM encoder.
    Args:
        num_units (int): the number of units in each layer
        num_layers_main (int): the number of layers of the main task
        num_layers_sub (int): the number of layers of the sub task
        num_classes_main (int): the number of classes of target labels in the
            main task (except for a blank label)
        num_classes_sub (int): the number of classes of target labels in the
            sub task (except for a blank label)
        lstm_impl (string): BasicLSTMCell or LSTMCell or LSTMBlockCell or
            LSTMBlockFusedCell.
            Choose the background implementation of tensorflow.
            Default is LSTMBlockCell (the fastest implementation).
        use_peephole (bool): if True, use peephole
        parameter_init (float): the range of uniform distribution to initialize
            weight parameters (>= 0)
        clip_activation (float): the range of activation clipping (> 0)
        num_proj (int): the number of nodes in recurrent projection layer
        bottleneck_dim (int): the dimensions of the bottleneck layer
        name (string, optional): the name of encoder
    """

    def __init__(self,
                 num_units,
                 num_layers_main,
                 num_layers_sub,
                 num_classes_main,
                 num_classes_sub,
                 lstm_impl,
                 use_peephole,
                 parameter_init,
                 clip_activation,
                 num_proj,
                 bottleneck_dim,
                 name='multitask_lstm_encoder'):

        self.num_units = num_units
        self.num_layers_main = num_layers_main
        self.num_layers_sub = num_layers_sub
        self.num_classes_main = num_classes_main
        self.num_classes_sub = num_classes_sub
        self.lstm_impl = lstm_impl
        self.use_peephole = use_peephole
        self.parameter_init = parameter_init
        self.clip_activation = clip_activation
        if lstm_impl != 'LSTMCell':
            self.num_proj = None
        elif num_proj not in [None, 0]:
            self.num_proj = int(num_proj)
        else:
            self.num_proj = None
        self.bottleneck_dim = int(bottleneck_dim) if bottleneck_dim not in [
            None, 0] else None
        self.name = name

        if self.num_layers_sub < 1 or self.num_layers_main < self.num_layers_sub:
            raise ValueError(
                'Set num_layers_sub between 1 to num_layers_main.')

    def __call__(self, inputs, inputs_seq_len,
                 keep_prob_input, keep_prob_hidden, keep_prob_output):
        """Construct model graph.
        Args:
            inputs (placeholder): A tensor of size`[B, T, input_size]`
            inputs_seq_len (placeholder): A tensor of size` [B]`
            keep_prob_input (placeholder, float): A probability to keep nodes
                in the input-hidden connection
            keep_prob_hidden (placeholder, float): A probability to keep nodes
                in the hidden-hidden connection
            keep_prob_output (placeholder, float): A probability to keep nodes
                in the hidden-output connection
        Returns:
            logits: A tensor of size `[T, B, input_size]` in the main task
            logits_sub: A tensor of size `[T, B, input_size]` in the sub task
            final_state: A final hidden state of the encoder in the main task
            final_state_sub: A final hidden state of the encoder in the sub task
        """
        # Dropout for the input-hidden connection
        outputs = tf.nn.dropout(
            inputs, keep_prob_input, name='dropout_input')

        # inputs: `[batch_size, max_time, input_size]`
        batch_size = tf.shape(inputs)[0]

        initializer = tf.random_uniform_initializer(
            minval=-self.parameter_init, maxval=self.parameter_init)

        # Hidden layers
        lstm_list = []
        for i_layer in range(1, self.num_layers_main + 1, 1):
            with tf.variable_scope('lstm_hidden' + str(i_layer), initializer=initializer) as scope:

                if self.lstm_impl == 'BasicLSTMCell':
                    lstm = tf.contrib.rnn.BasicLSTMCell(
                        self.num_units,
                        forget_bias=1.0,
                        state_is_tuple=True,
                        activation=tf.tanh)

                elif self.lstm_impl == 'LSTMCell':
                    lstm = tf.contrib.rnn.LSTMCell(
                        self.num_units,
                        use_peepholes=self.use_peephole,
                        cell_clip=self.clip_activation,
                        num_proj=self.num_proj,
                        forget_bias=1.0,
                        state_is_tuple=True)

                elif self.lstm_impl == 'LSTMBlockCell':
                    # NOTE: This should be faster than tf.contrib.rnn.LSTMCell
                    lstm = tf.contrib.rnn.LSTMBlockCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    # TODO: cell clipping (update for rc1.3)

                elif self.lstm_impl == 'LSTMBlockFusedCell':
                    raise NotImplementedError

                    # NOTE: This should be faster than
                    tf.contrib.rnn.LSTMBlockFusedCell
                    lstm = tf.contrib.rnn.LSTMBlockFusedCell(
                        self.num_units,
                        forget_bias=1.0,
                        # clip_cell=True,
                        use_peephole=self.use_peephole)
                    # TODO: cell clipping (update for rc1.3)

                else:
                    raise IndexError(
                        'lstm_impl is "BasicLSTMCell" or "LSTMCell" or ' +
                        '"LSTMBlockCell" or "LSTMBlockFusedCell".')

                # Dropout for the hidden-hidden connections
                lstm = tf.contrib.rnn.DropoutWrapper(
                    lstm, output_keep_prob=keep_prob_hidden)

                lstm_list.append(lstm)

            if i_layer == self.num_layers_sub:
                # Stack multiple cells
                stacked_lstm_sub = tf.contrib.rnn.MultiRNNCell(
                    lstm_list, state_is_tuple=True)

                # Ignore 2nd return (the last state)
                outputs_sub, final_state_sub = tf.nn.dynamic_rnn(
                    cell=stacked_lstm_sub,
                    inputs=inputs,
                    sequence_length=inputs_seq_len,
                    dtype=tf.float32)

                # Reshape to apply the same weights over the timesteps
                if self.num_proj is None:
                    outputs_sub = tf.reshape(outputs_sub,
                                             shape=[-1, self.num_units])
                else:
                    outputs_sub = tf.reshape(outputs_sub,
                                             shape=[-1, self.num_proj])

                with tf.variable_scope('output_sub') as scope:
                    logits_sub_2d = tf.contrib.layers.fully_connected(
                        outputs_sub, self.num_classes_sub,
                        activation_fn=None,
                        weights_initializer=tf.truncated_normal_initializer(
                            stddev=0.1),
                        biases_initializer=tf.zeros_initializer(),
                        scope=scope)

                    # Reshape back to the original shape
                    logits_sub = tf.reshape(
                        logits_sub_2d,
                        shape=[batch_size, -1, self.num_classes_sub])

                    # Convert to time-major: `[max_time, batch_size,
                    # num_classes]'
                    logits_sub = tf.transpose(logits_sub, (1, 0, 2))

                    # Dropout for the hidden-output connections
                    logits_sub = tf.nn.dropout(
                        logits_sub, keep_prob_output,
                        name='dropout_output_sub')
                    # NOTE: This may lead to bad results

        # Stack multiple cells
        stacked_lstm = tf.contrib.rnn.MultiRNNCell(
            lstm_list, state_is_tuple=True)

        # Ignore 2nd return (the last state)
        outputs, final_state = tf.nn.dynamic_rnn(
            cell=stacked_lstm,
            inputs=inputs,
            sequence_length=inputs_seq_len,
            dtype=tf.float32)

        # Reshape to apply the same weights over the timesteps
        if self.num_proj is None:
            outputs = tf.reshape(outputs, shape=[-1, self.num_units])
        else:
            outputs = tf.reshape(outputs, shape=[-1, self.num_proj])

        if self.bottleneck_dim is not None and self.bottleneck_dim != 0:
            with tf.variable_scope('bottleneck') as scope:
                outputs = tf.contrib.layers.fully_connected(
                    outputs, self.bottleneck_dim,
                    activation_fn=tf.nn.relu,
                    weights_initializer=tf.truncated_normal_initializer(
                        stddev=0.1),
                    biases_initializer=tf.zeros_initializer(),
                    scope=scope)

                # Dropout for the hidden-output connections
                outputs = tf.nn.dropout(
                    outputs, keep_prob_output,
                    name='dropout_output_main_bottle')

        with tf.variable_scope('output_main') as scope:
            logits_2d = tf.contrib.layers.fully_connected(
                outputs, self.num_classes_main,
                activation_fn=None,
                weights_initializer=tf.truncated_normal_initializer(
                    stddev=0.1),
                biases_initializer=tf.zeros_initializer(),
                scope=scope)

            # Reshape back to the original shape
            logits = tf.reshape(
                logits_2d, shape=[batch_size, -1, self.num_classes_main])

            # Convert to time-major: `[max_time, batch_size, num_classes]'
            logits = tf.transpose(logits, (1, 0, 2))

            # Dropout for the hidden-output connections
            logits = tf.nn.dropout(
                logits, keep_prob_output, name='dropout_output_main')
            # NOTE: This may lead to bad results

            return logits, logits_sub, final_state, final_state_sub

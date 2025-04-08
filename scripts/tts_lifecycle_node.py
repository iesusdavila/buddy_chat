#!/usr/bin/env python3

import rclpy
from rclpy.action import ActionClient
from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn 
from std_msgs.msg import Bool
from buddy_interfaces.msg import PersonResponse
from buddy_interfaces.action import ProcessResponse
from ament_index_python.packages import get_package_share_directory
from piper import PiperVoice
from playsound import playsound
import os
import threading
import tempfile
import wave

class TTSLifecycleNode(LifecycleNode):
    def __init__(self):
        super().__init__('tts_lifecycle_node')
        
        pkg_share_dir = get_package_share_directory('buddy_chat')
        self.tts_model_path = os.path.join(pkg_share_dir, 'models', 'TTS', 'es_MX-claude-high.onnx')
        self.tts_config_path = os.path.join(pkg_share_dir, 'models', 'TTS', 'es_MX-claude-high.onnx.json')
        
        self.voice = None
        
        self.stt_status_publisher = self.create_publisher(Bool, '/stt_terminado', 10)
        self.audio_playing_publisher = self.create_publisher(Bool, '/audio_playing', 10)

        self.create_subscription(PersonResponse, '/response_person', self.process_input_person, 10)
        self.text_person = None
        
        self._action_client = None
    
    def process_input_person(self, msg):
        """Process input from person response topic"""
        self.text_person = msg.text
    
    def on_configure(self, state):
        self.get_logger().info('Configuring TTS Node')
        
        try:
            self.voice = PiperVoice.load(
                model_path=self.tts_model_path,
                config_path=self.tts_config_path,
                use_cuda=True
            )
            
            return TransitionCallbackReturn.SUCCESS
        except Exception as e:
            return TransitionCallbackReturn.FAILURE
    
    def on_activate(self, state):
        self.get_logger().info('Activating TTS Node')
        
        self._action_client = ActionClient(self, ProcessResponse, '/response_llama')
        
        goal_thread = threading.Thread(target=self._listen_and_speak)
        goal_thread.start()
        
        return TransitionCallbackReturn.SUCCESS
    
    def on_deactivate(self, state):
        self.get_logger().info('Deactivating TTS Node')
        return TransitionCallbackReturn.SUCCESS
    
    def _listen_and_speak(self):
        """Listen for LLAMA responses and convert to speech"""
        if not self._action_client.wait_for_server(timeout_sec=1.0):
            return
        
        goal_msg = ProcessResponse.Goal()
        if self.text_person is not None:
            goal_msg.input_text = self.text_person
        else:
            return 

        self._action_client.wait_for_server()
        
        future = self._action_client.send_goal_async(
            goal_msg,
            feedback_callback=self._feedback_callback
        )

        self.get_logger().info('Waiting for goal to complete')
        
        rclpy.spin_until_future_complete(self, future)
    
    def _feedback_callback(self, feedback_msg):
        """Process feedback and convert text to speech"""
        chunk = feedback_msg.feedback.current_chunk
        
        if chunk and chunk != "[END_FINAL]":

            audio_status_msg = Bool()
            audio_status_msg.data = True
            self.audio_playing_publisher.publish(audio_status_msg)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as fp:
                with wave.open(fp.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(self.voice.config.sample_rate)
                    self.voice.synthesize(chunk, wav_file)
                
                playsound(fp.name)

                audio_status_msg = Bool()
                audio_status_msg.data = False
                self.audio_playing_publisher.publish(audio_status_msg)
        
        if feedback_msg.feedback.progress == 1.0:
            stt_status_msg = Bool()
            stt_status_msg.data = False
            self.stt_status_publisher.publish(stt_status_msg)
    
    def result_callback(self, future):
        """Procesa el resultado final de la acción"""
        result = future.result()

def main(args=None):
    rclpy.init(args=args)
    node = TTSLifecycleNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
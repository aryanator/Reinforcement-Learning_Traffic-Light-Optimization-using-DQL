import os
import sys
import traci
import numpy as np
from collections import deque
import random
import time
import traci
import subprocess
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Adam


# Ensure SUMO_HOME is in the system path
if 'SUMO_HOME' not in os.environ:
    sys.exit("Please declare the environment variable 'SUMO_HOME'")
tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
sys.path.append(tools)

def start_sumo():
    sumoBinary = "sumo"  # Use "sumo-gui" for GUI version if needed
    sumoCmd = [sumoBinary, "-c", "my_simulation.sumocfg", "--start", "--no-step-log", "--no-warnings"]
    # Start SUMO process
    sumo_process = subprocess.Popen(sumoCmd)
    # Wait for SUMO to initialize and connect to TraCI
    retries = 10
    while retries > 0:
        try:
            traci.init(port=8813)
            print("Connected to TraCI")
            return sumo_process  # Return the process handle
        except traci.TraCIException:
            print("Waiting for TraCI to initialize...")
            time.sleep(1)
            retries -= 1
    sys.exit("Failed to connect to TraCI after multiple attempts.")




# DQN Agent
class DQNAgent:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=2000)
        self.gamma = 0.95    # discount rate
        self.epsilon = 1.0   # exploration rate
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.learning_rate = 0.001
        self.model = self._build_model()

    def _build_model(self):
        model = Sequential()
        model.add(Dense(24, input_dim=self.state_size, activation='relu'))
        model.add(Dense(24, activation='relu'))
        model.add(Dense(self.action_size, activation='linear'))
        model.compile(loss='mse', optimizer=Adam())
        return model

    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        act_values = self.model.predict(state)
        return np.argmax(act_values[0])

    def replay(self, batch_size):
        minibatch = random.sample(self.memory, batch_size)
        for state, action, reward, next_state, done in minibatch:
            target = reward
            if not done:
                target = (reward + self.gamma *
                          np.amax(self.model.predict(next_state)[0]))
            target_f = self.model.predict(state)
            target_f[0][action] = target
            self.model.fit(state, target_f, epochs=1, verbose=0)
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

class TrafficEnvironment:
    def __init__(self):
        self.sumo_process = start_sumo()  # Start SUMO and connect to TraCI
        self.traffic_lights = traci.trafficlight.getIDList()

    def reset(self):
        traci.close()  # Close existing connection before resetting
        self.sumo_process = start_sumo()  # Restart SUMO simulation
        return self._get_state()

    def step(self, action):
        self._apply_action(action)
        traci.simulationStep()
        next_state = self._get_state()
        reward = self._get_reward()
        done = traci.simulation.getMinExpectedNumber() <= 0  # Check if simulation should end
        return next_state, reward, done

    def _get_state(self):
        state = []
        for tl in self.traffic_lights:
            phase = traci.trafficlight.getPhase(tl)
            waiting_time = sum(traci.lane.getWaitingTime(lane) for lane in traci.trafficlight.getControlledLanes(tl))
            state.extend([phase, waiting_time])
        return np.array(state)

    def _apply_action(self, action):
        # Ensure action is an array of integers (0 or 1) for each traffic light.
        for i, tl in enumerate(self.traffic_lights):
            if action[i] == 1:  # Change to next phase if action is set to 1
                current_phase = traci.trafficlight.getPhase(tl)
                traci.trafficlight.setPhase(tl, (current_phase + 1) % 4)

    def _get_reward(self):
        total_waiting_time = sum(traci.lane.getWaitingTime(lane) for tl in self.traffic_lights for lane in traci.trafficlight.getControlledLanes(tl))
        return -total_waiting_time

    def close(self):
        traci.close()
        if self.sumo_process:
            self.sumo_process.terminate()
            self.sumo_process.wait()

# Main training loop
def train_dqn():
    env = TrafficEnvironment()
    state_size = len(env._get_state())
    action_size = len(env.traffic_lights)
    agent = DQNAgent(state_size, action_size)
    batch_size = 32
    episodes = 100

    try:
        for e in range(episodes):
            state = env.reset()
            state = np.reshape(state, [1, state_size])
            total_reward = 0
            for time in range(3600):  # 1 hour simulation
                action = agent.act(state)
                next_state, reward, done = env.step(action)
                next_state = np.reshape(next_state, [1, state_size])
                agent.remember(state, action, reward, next_state, done)
                state = next_state
                total_reward += reward
                if done:
                    break
                if len(agent.memory) > batch_size:
                    agent.replay(batch_size)
            print(f"episode: {e}/{episodes}, total reward: {total_reward}")
    finally:
        env.close()

if __name__ == "__main__":
    train_dqn()
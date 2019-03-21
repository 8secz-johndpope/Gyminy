import gym_nao
import gym
import time

from gym import error, spaces, utils
from gym.utils import seeding

from stable_baselines.common.policies import MlpPolicy
from stable_baselines.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines.common import set_global_seeds
from stable_baselines import ACKTR, PPO2

from controller import Supervisor, Robot
new_model = False
episodes = 1000
load_path="PPO2_Balance"
tensorboard_path = "Balance"

env = gym.make('gym_nao_standUp-v0')
envVec = DummyVecEnv([lambda : env])


if new_model:
    print('Creating new model')
    model = PPO2(MlpPolicy, envVec, verbose=1, tensorboard_log = tensorboard_path)
else:
    print('Loading Model ' + load_path)
    model = PPO2.load(load_path, envVec, verbose=0, tensorboard_log = tensorboard_path)




print("Learning...")

model.learn(total_timesteps = episodes)

print("Finished Learning!")

model.save(load_path)

env.reset(master = True)

# for i in range(episodes):
#
#     obs = env.reset()
#     done = False
#     score = 0
#     j = 0
#
#     while done is False:
#         j += 1
#
#         action,_states = model.predict(obs)
#         obs,reward,done,_ = env.step(action)
#
#         print("Timestep: ", j, "     Reward: ", reward)
#
#         score += reward
#
#         #time.sleep(0.01)
#
#     print("==========================================================")
#     print("Episode ", i, " Terminated!")
#     print("Total Score = ", score)
#     print("Average Reward = ", score/i)

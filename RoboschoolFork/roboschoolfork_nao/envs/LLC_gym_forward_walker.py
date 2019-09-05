from roboschool.scene_abstract import cpp_household
from roboschool.scene_stadium import SinglePlayerStadiumScene
from .multiplayer import SharedMemoryClientEnv
from .gym_mujoco_xml_env import RoboschoolMujocoXmlEnv
import gym, gym.spaces, gym.utils, gym.utils.seeding
import numpy as np
import os, sys
import json
import random
import math
script_dir = os.path.dirname(__file__) #<-- absolute dir the script is in
class LLC_RoboschoolForwardWalker(SharedMemoryClientEnv):
    def __init__(self, power):
        self.power = power
        self.camera_x = 0
        self.walk_target_x = 1e3  # kilometer away
        self.walk_target_y = 0
        self.start_pos_x, self.start_pos_y, self.start_pos_z = 0, 0, 0
        self.camera_x = 0
        self.camera_y = 4.3
        self.camera_z = 45.0
        self.camera_follow = 0
        self.flag = 0
        self.phase = 0
        with open(os.path.join(script_dir, "AnimationsProcessed.json")) as file:
            self.animations = json.load(file)
        for i in range(len(self.animations)):
            for n in self.animations[i].keys():
                self.animations[i][n] = np.array(self.animations[i][n])
        self.rand_animation = random.choice(self.animations)
        with open(os.path.join(script_dir, "PartEquivalents.json")) as file:
            self.equivalents = json.load(file)
    def create_single_player_scene(self):
        return SinglePlayerStadiumScene(gravity=9.8, timestep=0.0165/4, frame_skip=4)

    def robot_specific_reset(self):
        for j in self.ordered_joints:
            initial_vel = 0
            if(j.name in self.initial_joint_position.keys()):
                initial_pos = self.real_position(self.initial_joint_position[j.name], j.limits()[0:2])
                #initial_pos += self.np_random.uniform( low=-0.1, high=0.1 )
            else:
                initial_pos = 0
            j.reset_current_position(initial_pos, initial_vel)
        self.feet = [self.parts[f] for f in self.foot_list]
        self.feet_contact = np.array([0.0 for f in self.foot_list], dtype=np.float32)
        self.scene.actor_introduce(self)
        self.initial_z = 0.45

    def apply_action(self, a):
        assert( np.isfinite(a).all() )
        #np.insert(a,[33,34,35,36,37,38,39,40,41,42],0) #freeze hands
        #print(a)
        delta = 0
        for n,j in enumerate(self.ordered_joints):
            #print(j.name)
            # j.set_motor_torque( self.power*j.power_coef*float(np.clip(a[n], -1, +1)) )
            target = self.real_position(a[n],j.limits()[0:2])
            actual = j.current_relative_position()
            delta += abs(target - actual[0])
            #print(j.name,target, actual[0],target - actual[0])
            j.set_servo_target(target,0.8,20.0,self.power*j.power_coef*.1)
        #print(delta)
        return delta
    # def get_action_position_distance(self, action):
    #     j = np.array([j.current_relative_position() for j in self.ordered_joints], dtype=np.float32)
    #     a = np.array(real_pos(action[])
    #     print("get_joints_relative_position")
    #     print(j)
    #     #input()
    #     return

    def calc_state(self):
        j = np.array([j.current_relative_position() for j in self.ordered_joints], dtype=np.float32).flatten()
        # even elements [0::2] position, scaled to -1..+1 between limits
        # odd elements  [1::2] angular speed, scaled to show -1..+1
        self.joint_speeds = j[1::2]
        #print(self.joint_speeds)
        #input()
        self.joints_at_limit = np.count_nonzero(np.abs(j[0::2]) > 0.99)
        body_pose = self.robot_body.pose()

        parts_xyz = np.array( [p.pose().xyz() for p in self.parts.values()] ).flatten()
        #self.body_xyz = (parts_xyz[0::3].mean(), parts_xyz[1::3].mean(), body_pose.xyz()[2])  # torso z is more informative than mean z
        self.body_xyz = body_pose.xyz()
        self.body_rpy = body_pose.rpy()
        z = self.body_xyz[2]
        r, p, yaw = self.body_rpy
        if self.initial_z is None:
            self.initial_z = z
        self.walk_target_theta = np.arctan2( self.walk_target_y - self.body_xyz[1], self.walk_target_x - self.body_xyz[0] )
        self.walk_target_dist  = np.linalg.norm( [self.walk_target_y - self.body_xyz[1], self.walk_target_x - self.body_xyz[0]] )
        self.angle_to_target = self.walk_target_theta - yaw

        self.rot_minus_yaw = np.array(
            [[np.cos(-yaw), -np.sin(-yaw), 0],
             [np.sin(-yaw),  np.cos(-yaw), 0],
             [           0,             0, 1]]
            )
        vx, vy, vz = np.dot(self.rot_minus_yaw, self.robot_body.speed())  # rotate speed back to body point of view

        more = np.array([
            abs(self.phase/30), #para que la red sepa en que paso va
            z-self.initial_z,
            np.sin(self.angle_to_target), np.cos(self.angle_to_target),
            0.3*vx, 0.3*vy, 0.3*vz,    # 0.3 is just scaling typical speed into -1..+1, no physical sense here
            r, p], dtype=np.float32)
        obs = np.clip( np.concatenate([more] + [j] + [self.feet_contact]), -5, +5)
        #print("obs len:",len(obs))
        return obs

    def calc_potential(self):
        # progress in potential field is speed*dt, typical speed is about 2-3 meter per second, this potential will change 2-3 per frame (not per second),
        # all rewards have rew/frame units and close to 1.0
        return - self.walk_target_dist / self.scene.dt

    electricity_cost     = -2.0    # cost for using motors -- this parameter should be carefully tuned against reward for making progress, other values less improtant
    stall_torque_cost    = -0.1    # cost for running electric current through a motor even at zero rotational speed, small
    foot_collision_cost  = -1.0    # touches another leg, or other objects, that cost makes robot avoid smashing feet into itself
    foot_ground_object_names = set(["floor"])  # to distinguish ground and other objects
    joints_at_limit_cost = -0.2    # discourage stuck joints

    def appendSpherical_np(self, xyz):
        ptsnew = np.hstack((xyz, np.zeros(xyz.shape)))
        xy = xyz[:,0]**2 + xyz[:,1]**2
        ptsnew[:,3] = np.sqrt(xy + xyz[:,2]**2)
        ptsnew[:,4] = np.arctan2(np.sqrt(xy), xyz[:,2]) # for elevation angle defined from Z-axis down
        #ptsnew[:,4] = np.arctan2(xyz[:,2], np.sqrt(xy)) # for elevation angle defined from XY-plane up
        ptsnew[:,5] = np.arctan2(xyz[:,1], xyz[:,0])
        return ptsnew

    def step(self, a):
        #input()
        # print(self.get_joints_relative_position())
        action_delta = 0
        if not self.scene.multiplayer:  # if multiplayer, action first applied to all robots, then global step() called, then step() for all robots with the same actions
            action_delta = self.apply_action(a)
            self.scene.global_step()

        state = self.calc_state()  # also calculates self.joints_at_limit

        if self.phase%15 == 0:
            if self.phase >14:
                self.rand_animation = random.choice([self.animations[0], self.animations[4]])
            else:
                self.rand_animation = random.choice([self.animations[1], self.animations[5]])

        self.phase = (self.phase + 1)%30


        #print(self.phase)
        body_pose = self.robot_body.pose()
        self.flag=[]
        self.flag.append(self.scene.cpp_world.debug_sphere(body_pose.xyz()[0], body_pose.xyz()[1],body_pose.xyz()[2], 0.05, 0x10FF10))
        positions = []
        names = []
        for p in sorted(list(self.parts.keys())):
            if(p in ["RElbow","LElbow","RThig","LThig","RTibia","LTibia","r_wrist","l_wrist","RHip","LHip","r_ankle","l_ankle"]):
                # x1,y1,z1 = body_pose.xyz()
                # x2,y2,z2 = self.parts[p].pose().xyz()
                # balls = 10
                # for i in range(balls):
                #     xs2 = (x2 - x1)*i/balls + x1
                #     ys2 = (y2 - y1)*i/balls + y1
                #     zs2 = (z2 - z1)*i/balls + z1
                #     self.flag.append(self.scene.cpp_world.debug_sphere(xs2, ys2, zs2, 0.01, 0x10FF10))
                # self.flag.append(self.scene.cpp_world.debug_sphere(x2, y2, z2, 0.03, 0x10FF10))
                relative_pose = np.array(self.parts[p].pose().xyz()) - np.array(body_pose.xyz())
                # if (self.phase%30 > 14):
                #     relative_pose[0] = relative_pose[0] * -1
                positions.append(list(relative_pose))
                equivalent = self.equivalents[p]
                names.append(equivalent)
        positions = self.appendSpherical_np(np.array(positions))
        delta_angles = 0

        pose_discount = 0
        for n in range(len(names)):
            x1,y1,z1 = body_pose.xyz()
            pos = self.polar2cart( positions[n,3] , self.rand_animation[names[n]][self.phase%15,[4]],self.rand_animation[names[n]][ self.phase%15 ,[5]])
            # if (self.phase%30 > 14):
            #     pos[0] *= -1
            #     pos[1] *= -1
            pos[0] += x1 + 0.5
            pos[1] += y1
            pos[2] += z1
            self.flag.append(self.scene.cpp_world.debug_sphere(pos[0], pos[1], pos[2], 0.02, 0xFF1010))
            delta = np.power(positions[n,[4,5]] - self.rand_animation[names[n]][ self.phase%15 ,[4,5]], 2)
            #print(names[n], delta)
            delta = np.sum(delta)
            pose_discount+=delta
        #print(pose_discount/100)
        alive = float(self.alive_bonus(state[0]+self.initial_z, self.body_rpy[1]))   # state[0] is body height above ground, body_rpy[1] is pitch
        done = alive < 0
        if not np.isfinite(state).all():
            print("~INF~", state)
            done = True

        potential_old = self.potential
        self.potential = self.calc_potential()
        progress = float(self.potential - potential_old)

        feet_collision_cost = 0.0

        for i,f in enumerate(self.feet):
            contact_names = set(x.name for x in f.contact_list())
            #print("CONTACT OF '%s' WITH %s" % (f.name, ",".join(contact_names)) )
            self.feet_contact[i] = 1.0 if (self.foot_ground_object_names & contact_names) else 0.0
            if contact_names - self.foot_ground_object_names:
                feet_collision_cost += self.foot_collision_cost

        # electricity_cost  = self.electricity_cost  * float(np.abs(a*self.joint_speeds).mean())  # let's assume we have DC motor with controller, and reverse current braking
        # electricity_cost += self.stall_torque_cost * float(np.square(a).mean())
        height_discount = -abs(0.37 - self.body_xyz[2]) * 3 - (abs(self.body_rpy[0]) + abs(self.body_rpy[1]) + abs(self.body_rpy[2]))/3
        joints_at_limit_cost = float(self.joints_at_limit_cost * self.joints_at_limit)

        self.rewards = [
            alive,
            progress,
            #delta = np.power(positions[n,[4,5]] - self.rand_animation[names[n]]
            pose_discount/-5,
            #height_discount,
            #action_delta/-50,
            # electricity_cost,
            #joints_at_limit_cost,
            feet_collision_cost
            ]

        self.frame  += 1
        if (done and not self.done) or self.frame==self.spec.max_episode_steps:
            self.phase = 0
            self.episode_over(self.frame)
        self.done   += done   # 2 == 1+True
        self.reward += sum(self.rewards)
        self.HUD(state, a, done)
        return state, sum(self.rewards), bool(done), {}

    def episode_over(self, frames):
        pass

    def camera_adjust(self):
        #self.camera_dramatic()
        self.camera_simple_follow()

    def camera_simple_follow(self):
        x, y, z = self.body_xyz
        self.camera_x = 0.98*self.camera_x + (1-0.98)*x
        self.camera.move_and_look_at(self.camera_x, y-1.0, 0.1, x, y, 0.4)

    def camera_dramatic(self):
        pose = self.robot_body.pose()
        speed = self.robot_body.speed()
        x, y, z = pose.xyz()
        if 1:
            camx, camy, camz = speed[0], speed[1], 2.2
        else:
            camx, camy, camz = self.walk_target_x - x, self.walk_target_y - y, 2.2

        n = np.linalg.norm([camx, camy])
        if n > 2.0 and self.frame > 50:
            self.camera_follow = 1
        if n < 0.5:
            self.camera_follow = 0
        if self.camera_follow:
            camx /= 0.1 + n
            camx *= 2.2
            camy /= 0.1 + n
            camy *= 2.8
            if self.frame < 1000:
                camx *= -1
                camy *= -1
            camx += x
            camy += y
            camz  = 1.8
        else:
            camx = x
            camy = y + 4.3
            camz = 2.2
        #print("%05i" % self.frame, self.camera_follow, camy)
        smoothness = 0.97
        self.camera_x = smoothness*self.camera_x + (1-smoothness)*camx
        self.camera_y = smoothness*self.camera_y + (1-smoothness)*camy
        self.camera_z = smoothness*self.camera_z + (1-smoothness)*camz
        self.camera.move_and_look_at(self.camera_x, self.camera_y, self.camera_z, x, y, 0.6)

    def real_position(self, relative_pos, limits):
        min, max = limits
        real_pos = ((relative_pos + 1) / 2) * (max - min) + min
        return real_pos
    def polar2cart(self, r, theta, phi):
        cart = np.array([ r * math.sin(theta) * math.cos(phi), r * math.sin(theta) * math.sin(phi), r * math.cos(theta) ])
        return cart
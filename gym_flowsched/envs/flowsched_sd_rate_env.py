import os,sys
import numpy as np
from numpy import genfromtxt
from gym import Env, spaces
from gym.utils import seeding

def categorical_sample(prob_n, np_random):
    """
    Sample from categorical distribution
    Each row specifies class probabilities
    """
    prob_n = np.asarray(prob_n)
    csprob_n = np.cumsum(prob_n)
    return (csprob_n > np_random.rand()).argmax()

class FlowSchedSdRateEnv(Env):
    """
    Description:
    Consider a network with pre-determined topology in which flows arrive at
    different timeslots. In each episode, flows arrive one by one, the bandwidth
    capacity on each link changes, and the agent chooses a protocol
    for all flows on each given link.

    Initialization:
    There are in total 20 levels of bandwidth capacity on each link, 3 protocol
    choices, and 10 flows coming one by one per episode.

    Observations:
    There are 20 states on each link corresponding to 20 levels of bandwidth
    capacity on each link.

    Actions:
    There are 3 actions on each link:
    TCP Cubic --> 0
    TCP Reno  --> 1
    TCP Vegas --> 2

    Rewards:
    Rewards represent transmission rates per flow on each link.

    Probability transition matrix on each link i:
    P[ s[i] ][ a[i] ]= [(probability, newstate, reward, done), ...]
    """
    def __init__(self):
        """
        self.nF[1]
        self.rm_size[self.nL, self.nF]: remaining size
        new_flow_size_link[self.nL]: size of new flows on each link
        self.s[self.nL]: state on each link
        a[self.nL]: action on each link
        transitions: self.nS tuples, where each tuple is (probability, nextstate)
        wt[self.nL, self.nS]: produced given action for all links
        self.rate_link[self.nL, self.nS]: total achieved transmission rate each link
        self.flow_time_link[self.nL, self.nF]
        self.bw_cap_link[self.nL, self.nS]: bandwidth capacity for each state on each link

        """
        self.seed(0)
        self.nL = 6
        self.nF = 10
        self.nS = 20
        self.nA = 5
        self.isd = [ [1/self.nS for _ in range(self.nS)] for _ in range(self.nL)]
        self.action_space = spaces.Box(low=0,
                                       high=1,
                                       shape=(self.nL,),
                                       dtype=np.float32)
        #self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(np.asarray([0]*self.nL),
                                            np.asarray([self.nS]*self.nL),
                                            dtype=np.int64)
        # Probability transition matrix is the same on each link
        state_dist = genfromtxt('data/state_dist.txt')
        self.P = {s: {disc_a: [] for disc_a in range(self.nA)} for s in range(self.nS)}
        for s in range(self.nS):
            for disc_a in range(self.nA):
                for newstate in range(self.nS):
                    self.P[s][disc_a].append((state_dist[newstate], newstate, 1, False))



        self.flowtime_episodes = []
        # code reuse
        self.reset()

    def _get_weight(self, a):
        # First, compute the mean of the effective transmission rate using the exponential function
        # i.e., the middle of the range of sending rate (actions) yields a largest mean 
        # of the effective transmission rate 
        mu = 0.2 # 0.5 fraction of the feasible range of sending rate achieves the highest mean 
        # of effective transmission rate
        wt_mean =  np.e**(-(a-mu)**2) # wt_mean is in (0,1]
        # print("The mean of effective transmission rate is:{}".format(wt_mean))
        #transmission rate that sending rate (action) a can achieve

        # Then, sample the effective transmission rate from a Gaussian distribution 
        # with mean = wt_mean under the action a 
        sigma = 0.2 # arbitrary setting
        ini_small = [0.01 for _ in range(self.nL)] # smallest positive realized wt 
        wt = np.array([np.minimum( np.maximum(ini_small,np.random.normal(wt_mean)), 1 ) for _ in range(self.nS)])
        wt = np.transpose(wt)
        return wt

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def reset(self):
        self.lastaction = None
        self.rm_size = np.zeros((self.nL,self.nF))
        self.flow_time_link = np.zeros((self.nL, self.nF))
        self.num_flows = 0
        self.s = np.zeros(self.nL, dtype=np.int)
        self.bw_cap_link = np.zeros((self.nL, self.nS))
        self.rate_link = np.zeros((self.nL, self.nS))

        wt = np.array([[0.5 for _ in range(self.nS)] for _ in range(self.nL)])
        for iL in range(self.nL):
            self.s[iL] = categorical_sample(self.isd[iL], self.np_random)
            self.bw_cap_link[iL] = [x+1 for x in range(self.nS)]
            self.rate_link[iL] = np.matmul(wt[iL],np.diag(self.bw_cap_link[iL]))
            # shape of self.rate_link[iL]: [1, nS] (1*nS)
        return self.s

    def render(self, mode='human'):
        return self.flowtime_episodes

    def _get_flow_time(self, RmSize, FlowTime, Rate):
        """
        RmSize[self.nF] = self.rm_size[iL], remaining sizes of each flows on the iL-th link
        FlowTime[self.nF] = self.flow_time_link[iL], flow-times of each flows on the iL-th link
        Rate (constant) = self.rate_link[iL][s], total transmission rate of current flows on iL
        """

        RmSize_pos = [x for x in RmSize if x>0]
        num_alive_flows = np.size(RmSize_pos)
        time_out = 0

        while time_out < 1 and  num_alive_flows>0:
            shortest_flowsize = min(RmSize_pos)
            rate_per_flow = Rate / (num_alive_flows if num_alive_flows > 0 else 1) # same rate for all flows
            time_shortest_flow = shortest_flowsize / rate_per_flow
            alive_flag = []

            for x in RmSize:
                if x>0:
                    alive_flag.append(1) # alive flows
                else:
                    alive_flag.append(0) # finished flows or flows that haven't arrived
            alive_flag = np.array(alive_flag)        

            if time_shortest_flow > 1-time_out: # no more flows finished by this timeslot
                FlowTime += (1-time_out) * alive_flag
                RmSize = [max(x - rate_per_flow * (1-time_out), 0) for x in RmSize]
                time_out = 1 # timeslot ends
            else:
                FlowTime += time_shortest_flow * alive_flag
                RmSize = [max(x - shortest_flowsize, 0) for x in RmSize]
                time_out += time_shortest_flow

            # Update the number and sizes of remaining flows and the transmission rate per flow    
            RmSize_pos = [x for x in RmSize if x>0]
            num_alive_flows = np.size(RmSize_pos)

        return RmSize, FlowTime

    def step(self, a):
        # One flow arrives per timestep until reaching a total of self.nF flows
        if self.num_flows < self.nF:
            if self.np_random.rand() > 0.5:
                path = np.array([1, 1, 0, 1, 0, 1]) # first path of the 6-link diamond network
            else:
                path = np.array([1, 0, 1, 0, 1, 0]) # second path of the 6-link diamond network
            #self.rm_size[...,self.num_flows] += (8 * self.np_random.rand() + 2) * path # assign a new flow onto its path
            self.rm_size[...,self.num_flows] += 10 * path
            self.num_flows += 1

        p_vec, newstate_vec, reward_vec = [], [], []
        
        # Use continuous actions as the values of sending rates
        # but group the actions for each link to self.nA ranges 
        # so that each group has a distinct transition
        # print('actions shape:{}'.format(a.shape))
        # print(type(a))

        # Todo: reshape a from an arbitrary shape to a list with each element in [0,1]
        a = list(map(lambda x: 1/(1+np.e**x), a))
        a = np.array(a)
        wt = self._get_weight(a)
        disc_a = list(map(lambda x: min(int(x*self.nA), self.nA-1), a)) # actions for each link is in [0, 1]; if some action ==1, it will go to group 4

        for iL in range(self.nL):
            # if a[iL]==5:
            #     print("action group on some link is:{}".format(a[iL]))
            transitions = self.P[ self.s[iL] ][ disc_a[iL] ]
            i_trans = categorical_sample([t[0] for t in transitions], self.np_random)
            p, newstate, _, _ = transitions[i_trans]
            p_vec.append(p) # transition for the state vector over all links
            self.s[iL] = newstate

            # Todo: compute effective transmission rate for all using the weight (wt) times bandwidth capacity 
            # print("wt shape:{}".format(wt.shape))
            # print("bw shape:{}".format(self.bw_cap_link.shape))
            self.rate_link[iL] = np.matmul(wt[iL],np.diag(self.bw_cap_link[iL])) # to be revised 
            reward = self.rate_link[iL][int(self.s[iL])] # to be revised 
            # directly compute reward from wt

            self.rm_size[iL], self.flow_time_link[iL] = self._get_flow_time(self.rm_size[iL],
                                                                          self.flow_time_link[iL],
                                                                          self.rate_link[iL][int(self.s[iL])])
            newstate_vec.append(newstate)
            reward_vec.append(reward)

        if ( self.rm_size == np.zeros((self.nL, self.nF)) ).all() and self.num_flows >= self.nF:
            print('Flow time on link {} is: {}'.format(0, self.flow_time_link[0]))
            self.flowtime_episodes = sum(self.flow_time_link.max(0))
            done = True
        else:
            done = False

        #print(newstate_vec, sum(reward_vec), done, {"prob": p_vec})
        return (newstate_vec, min(reward_vec), done, {"prob": p_vec})


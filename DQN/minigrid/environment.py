from __future__ import annotations

import time
import math
import torch
import pygame
import numpy as np
import gymnasium as gym

from abc import abstractmethod
from minigrid.grid import Grid
from typing import Iterable, TypeVar
from minigrid.world import Goal, Agent, Obstacle, Wall
from utils import Actions, COLOR_NAMES, TILE_PIXELS


T = TypeVar("T")

class MultiGridEnv(gym.Env):
    def __init__(self, args, agents):
        self.clock = None
        self.window = None
        self.agents = agents
        self.goals = []
        self.obstacles = []
        self.seed = args.seed
        self.actions = Actions
        self.screen_size = 640
        self.render_size = None
        self.gamma = args.gamma

        # Environment configuration
        self.entities = []
        self.step_count = 0
        self.num_collected = 0
        self.width = args.grid_size
        self.height = args.grid_size
        self.see_through_walls = True
        self.obs_size = args.obs_size
        self.num_goals = args.num_goals
        self.max_steps = args.episode_steps
        self.num_obstacles = args.num_obstacles
        self.max_edge_dist = args.max_edge_dist
        self.grid = Grid(self.width, self.height)
        self.agent_view_size = args.agent_view_size
        
        # Rendering attributes
        self.highlight = True
        self.tile_size = TILE_PIXELS
        self.window_name = "Custom MiniGrid"

        # Reward values
        self.reward_goal = args.reward_goal
        self.penalty_obstacle = args.penalty_obstacle
        self.penalty_goal = args.penalty_goal
        self.penalty_invalid_move = args.penalty_invalid_move

        # Calculate the actual number of cells, excluding the outer walls
        self.total_cells = (self.width - 2) * (self.height - 2)
        # Initialize seen_cells to only track the inner grid
        self.seen_cells = np.zeros((self.width - 2, self.height - 2), dtype=bool)
        
    def reset(self, render):
        # To keep the same grid for each episode, call env.seed() with
        # the same seed before calling env.reset()
        super().reset(seed=int(time.time()))
        obs = []
        self.goals = []
        self.entities = []
        self.obstacles = []
        
        self.step_count = 0
        self.num_collected = 0
        self.seen_cells.fill(False)


        for agent in self.agents:
            agent.reset()

        self._gen_grid(self.width, self.height)

        for agent in self.agents:
            obs.append(self._get_obs(agent))

        if render: 
            self.render()
     
        return obs

    @abstractmethod
    def _gen_grid(self, width, height):
        self.grid = Grid(width, height)

        # Generate the surrounding walls
        self.grid.wall_rect(0, 0, width, height)

        # Place agents based on their number
        num_agents = len(self.agents)

        if num_agents == 1:
            # Place the agent at the bottom center
            x, y = width // 2, height - 2
            self._place_agent(self.agents[0], x, y)

        elif num_agents == 2:
            # Place agents at bottom left and right corners
            self._place_agent(self.agents[0], 1, height - 2)
            self._place_agent(self.agents[1], width - 2, height - 2)

        elif num_agents == 3:
            # Place agents at bottom corners and top middle
            self._place_agent(self.agents[0], 1, height - 2)
            self._place_agent(self.agents[1], width - 2, height - 2)
            self._place_agent(self.agents[2], width // 2, 1)

        elif num_agents == 4:
            # Place agents at all four corners
            self._place_agent(self.agents[0], 1, 1)
            self._place_agent(self.agents[1], width - 2, 1)
            self._place_agent(self.agents[2], 1, height - 2)
            self._place_agent(self.agents[3], width - 2, height - 2)

        else:
            # Evenly spread agents around the edges
            positions = self._get_edge_positions(width, height, num_agents)
            for agent, pos in zip(self.agents, positions):
                self._place_agent(agent, pos[0], pos[1])

        # Place goals randomly in the grid
        for _ in range(self.num_goals):
            self._place_object(Goal())

        # Place obstacles randomly in the grid
        for _ in range(self.num_obstacles):
            self._place_object(Obstacle())

    def _place_agent(self, agent, x, y):
        agent.init_pos = (x, y)
        agent.cur_pos = (x, y)
        agent.direction = 3  # Assuming 3 is the default direction
        self.grid.set_agent(x, y, agent)
        self.entities.append(agent)

    def _place_object(self, obj):
        while True:
            x, y = self._rand_pos(1, self.width - 2, 1, self.height - 2)
            if not self.grid.get(x, y):
                self.grid.set(x, y, obj)
                obj.cur_pos = (x, y)
                if isinstance(obj, Goal):
                    self.goals.append(obj)
                elif isinstance(obj, Obstacle):
                    self.entities.append(obj)
                    self.obstacles.append(obj)
                break

    def _get_edge_positions(self, width, height, num_agents):
        positions = []
        total_edge_length = 2 * (width - 2) + 2 * (height - 2)
        spacing = total_edge_length / num_agents

        current_pos = 0
        for i in range(num_agents):
            edge_pos = int(current_pos)
            if edge_pos < width - 2:
                positions.append((edge_pos + 1, 1))  # Top edge
            elif edge_pos < width + height - 4:
                positions.append((width - 2, edge_pos - width + 3))  # Right edge
            elif edge_pos < 2 * width + height - 6:
                positions.append((2 * width + height - 7 - edge_pos, height - 2))  # Bottom edge
            else:
                positions.append((1, total_edge_length - edge_pos))  # Left edge

            current_pos += spacing

        return positions

    def _get_obs(self, agent):
        obs = []
        obs.extend(agent.cur_pos)

        # Find goals within the agent's field of view
        goals_in_fov = []
        for goal in self.goals:
            dist = math.sqrt((agent.cur_pos[0] - goal.cur_pos[0])**2 + (agent.cur_pos[1] - goal.cur_pos[1])**2)
            if dist <= self.max_edge_dist and not goal.collected:
                goals_in_fov.append((goal, dist))

        # Sort goals by distance and take the 3 closest
        goals_in_fov.sort(key=lambda x: x[1])
        goals_in_fov = goals_in_fov[:3]

        # Add goal information to the observation
        for goal, _ in goals_in_fov:
            obs.extend(goal.cur_pos)
            obs.append(int(goal.collected))

        # Pad with dummy values if necessary
        num_goals = len(goals_in_fov)
        padding = [0, 0, 0] * (3 - num_goals)
        obs.extend(padding)

        # Update agent's goals
        agent.goals = [goal for goal, _ in goals_in_fov]

        # [agent_x, agent_y, goal1_x, goal1_y, goal1_collected, goal2_x, goal2_y, goal2_collected, goal3_x, goal3_y, goal3_collected]
        agent.obs = torch.tensor(obs)
        return agent.obs

    def encode(self, cell, agent):
        if cell is None:
            return 0
        elif isinstance(cell, Goal) and cell.color == 'green':
            return 1
        elif isinstance(cell, Obstacle) or isinstance(cell, Wall) or (isinstance(cell, Agent) and cell != agent) or cell.color == 'grey':
            return 2
        else:
            raise ValueError("Encode error.")
        
    def _handle_overlap(self, i, fwd_pos, fwd_cell):
        reward = 0
        if isinstance(fwd_cell, Goal) and not fwd_cell.collected:
            reward = self._reward(self.reward_goal)
            fwd_cell.color = 'grey'
            fwd_cell.collected = True
            self.num_collected += 1
        elif isinstance(fwd_cell, Goal) and fwd_cell.collected:
            reward = self._reward(self.penalty_goal)
        elif isinstance(fwd_cell, Obstacle):
            reward = self._reward(self.penalty_obstacle)
        else:
            print(f'fwd_cell = {fwd_cell}')
            raise ValueError("_handle_overlap error.")

        self.grid.set_agent(*fwd_pos, self.agents[i])
        self.grid.set_agent(*self.agents[i].cur_pos, None)
        self.agents[i].cur_pos = fwd_pos
        return reward

    def step(self, actions, render):
        obs = []
        dones = [False] * len(self.agents)
        self.step_count += 1
        rewards = np.zeros(len(self.agents))

        for i, action in enumerate(actions):
            agent_pos = self.agents[i].cur_pos
            
            # Move up
            if action == self.actions.up:
                new_pos = (agent_pos[0], agent_pos[1] - 1)
            # Move down
            elif action == self.actions.down:
                new_pos = (agent_pos[0], agent_pos[1] + 1)
            # Move left
            elif action == self.actions.left:
                new_pos = (agent_pos[0] - 1, agent_pos[1])
            # Move right
            elif action == self.actions.right:
                new_pos = (agent_pos[0] + 1, agent_pos[1])

            # Check if the new position is valid (not a wall and within bounds)
            cell = self.grid.get(*new_pos)
            agent = self.grid.get_agent(*new_pos)

            # If move is valid and space is empty
            if cell is None and agent is None and 0 <= new_pos[0] < self.width and 0 <= new_pos[1] < self.height:
                self.grid.set_agent(*new_pos, self.agents[i])
                self.grid.set_agent(*self.agents[i].cur_pos, None)
                self.agents[i].cur_pos = new_pos
            # If move is valid but involves an overlap
            elif cell and cell.can_overlap():
                rewards[i] = self._handle_overlap(i, new_pos, cell)
            # If move is not valid
            else:
                rewards[i] = self._reward(-5)

            if self.step_count >= self.max_steps or self.num_collected >= self.num_goals:
                dones[i] = True

        dones = [True if any(dones) else d for d in dones]

        self._update_seen_cells()
        seen_percentage = self._calculate_seen_percentage()

        if any(dones):
            info = {
                "goals_collected": self.num_collected,
                "goals_percentage": (self.num_collected / self.num_goals) * 100,
                "seen_percentage": seen_percentage
            }
        else:
            info = {"seen_percentage": seen_percentage}

        for agent in self.agents:
            obs.append(self._get_obs(agent))

        if render:
            self.render()
        
        return obs, rewards, dones, info

    def _update_seen_cells(self):
        for i in range(1, self.width - 1):
            for j in range(1, self.height - 1):
                for agent in self.agents:
                    dist = math.sqrt((i - agent.cur_pos[0])**2 + (j - agent.cur_pos[1])**2)
                    if dist <= self.max_edge_dist:
                        # Map the coordinates to the inner grid
                        self.seen_cells[i-1, j-1] = True
                        break  # Once a cell is seen by any agent, we can move to the next cell
                    
    def _calculate_seen_percentage(self):
        return np.sum(self.seen_cells) / self.total_cells * 100
    
    def render(self):
        img = self.get_full_render(self.highlight, self.tile_size)
        img = np.transpose(img, axes=(1, 0, 2))

        if self.render_size is None:
            self.render_size = img.shape[:2]
        if self.window is None:
            pygame.init()
            pygame.display.init()
            self.window = pygame.display.set_mode((self.screen_size, self.screen_size))
            pygame.display.set_caption("minigrid")
        if self.clock is None:
            self.clock = pygame.time.Clock()
        surf = pygame.surfarray.make_surface(img)

        # Create background
        offset = surf.get_size()[0] * 0.1
        bg = pygame.Surface((int(surf.get_size()[0] + offset), int(surf.get_size()[1] + offset)))
        bg.convert()
        bg.fill((255, 255, 255))
        bg.blit(surf, (offset / 2, 0))
        bg = pygame.transform.smoothscale(bg, (self.screen_size, self.screen_size))

        # Blit the line surface onto the background
        self.window.blit(bg, (0, 0))
        pygame.event.pump()
        pygame.display.flip()

    def get_full_render(self, highlight, tile_size):
        highlight_masks = np.zeros((self.width, self.height), dtype=bool)

        for i in range(self.width):
            for j in range(self.height):
                # Compute the Euclidean distance from the agent's position
                for agent in self.agents:
                    dist = math.sqrt((i - agent.cur_pos[0])**2 + (j - agent.cur_pos[1])**2)
                    if dist <= self.max_edge_dist:
                        highlight_masks[i, j] = True
        
        img = self.grid.render(tile_size,highlight_mask=highlight_masks if highlight else None)
        return img

    def _reward(self, reward):
        return reward * (self.gamma ** self.step_count)
    
    def _rand_int(self, low, high):
        return self.np_random.integers(low, high)

    def _rand_float(self, low, high):
        return self.np_random.uniform(low, high)

    def _rand_bool(self):
        return (self.np_random.integers(0, 2) == 0)

    def _rand_elem(self, iterable: Iterable[T]):
        lst = list(iterable)
        idx = self._rand_int(0, len(lst))
        return lst[idx]

    def _rand_subset(self, iterable: Iterable[T], num_elems: int):
        lst = list(iterable)
        assert num_elems <= len(lst)
        out: list[T] = []
        while len(out) < num_elems:
            elem = self._rand_elem(lst)
            lst.remove(elem)
            out.append(elem)
        return out

    def _rand_color(self):
        return self._rand_elem(COLOR_NAMES)

    def _rand_pos(self, xLow, xHigh, yLow, yHigh):
        return (self.np_random.integers(xLow, xHigh),self.np_random.integers(yLow, yHigh))
    
    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()
            self.window = None

#!/usr/bin/env python3
# -- coding: utf-8 --

import os
import sys
import rospy
import math
import random
import time
import numpy as np
from sensor_msgs.msg import PointCloud
from geometry_msgs.msg import Point32, Point
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import Header
import sensor_msgs.point_cloud2 as pc2
from sensor_msgs.msg import PointCloud2
from sensor_msgs import point_cloud2
from macaron_06.msg import lidar_info
from math import *

class MissionTracking:
    def __init__(self):
        rospy.init_node('mission_tracking_node')

        self.raw = [] 
        self.center_offset = 1.3  # center 이격 거리

        self.marker_array_pub = rospy.Publisher('/marker_array', MarkerArray, queue_size=1)
        self.track_line_pub = rospy.Publisher('/track_line', PointCloud, queue_size=1)
        rospy.Subscriber('/cluster', lidar_info, self.point_callback)
        self.pose_sub = rospy.Subscriber('/current_pose', Point, self.pose_callback, queue_size=1)

        self.pose = [0.0,0.0]
        self.heading = 0.0

    def pose_callback(self, data):
        self.pose = [data.x, data.y]
        self.heading = data.z

    def tf2tm(self, no_z_points, x, y, heading):
        obs_tm=np.empty((1,3))
        T = [[cos(heading), -1*sin(heading), x], \
             [sin(heading),    cos(heading), y], \
             [      0     ,        0       , 1]] 
        for point in no_z_points:
            obs_tm = np.append(obs_tm,[np.dot(T,np.transpose([point[0]+1, point[1],1]))],axis=0) # point[0] -> 객체를 subscribe할 수 없음 오류
        obs_tm[:,2]=0
        obs_tm = np.delete(obs_tm, (0), axis = 0) 
        return obs_tm


    def point_callback(self, input_rosmsg):
        ''' 
        포인트 클라우드를 콜백으로 받아 처리하는 함수입니다.
        
        Args:
            input_rosmsg: ROS 메시지로 전달된 포인트 클라우드 데이터
        '''
        # 포인트 클라우드 데이터를 배열로 변환 (x, y, z 좌표만 추출)
        pcd = []
        for point in point_cloud2.read_points(input_rosmsg.data, field_names=("x", "y", "z", "intensity")):
            pcd.append(point)
        pcd = np.array(pcd)[:, :3]
        
        if pcd.shape[0] == 0:
            return

        cluster_indices = list(input_rosmsg.clusters)
        cone_indices = list(input_rosmsg.cones)

        if len(cluster_indices) == 0 or len(cone_indices) == 0:
            return

        clusters = []
        count = 0
        
        for indice_size in input_rosmsg.clusterSize:
            indice = cluster_indices[count: count + indice_size]
            count += indice_size

            clusters.append(pcd[indice, :])

        cones = [clusters[i] for i in cone_indices]
        
        centroids = []
        for person in cones:
            centroids.append(np.mean(person, axis=0))
        centroids = np.array(centroids)
        centroids= centroids.tolist()
        #print(centroids)
        direct_points = [point for point in centroids if np.sqrt(point[0] ** 2 + point[1] ** 2) <= 4]

        if direct_points:
            # direct_points에 있는 점들 중에 y가 양수인 점과 음수인 점 확인
            left_candidates = [point for point in direct_points if point[1] > 0 and point[0] > -1]
            right_candidates = [point for point in direct_points if point[1] < 0 and point[0] > -1]

            # 가장 x 값이 작은 점 선택
            left_point = min(left_candidates, key=lambda point: point[0], default=None) if left_candidates else None
            right_point = min(right_candidates, key=lambda point: point[0], default=None) if right_candidates else None

            # print(f"left_point: {left_point}, right_point: {right_point}")

            left_line = []
            right_line = []

            # NumPy 배열이나 None이 아닌지를 명확히 확인하도록 수정
            if left_point is not None and len(left_point) > 0:
                # left_line.append([-1, 1])
                left_line.append([left_point[0], left_point[1]])

            if right_point is not None and len(right_point) > 0:
                # right_line.append([-1, -1])
                right_line.append([right_point[0], right_point[1]])

            # 가장 가까운 점들을 찾아 left_line과 right_line 확장
            def find_closest_point_left(current_point, points):
                min_dist = float('inf')
                closest_point = None
                for point in points:
                    if point[0] > 0:  # x가 양수인 점들만 고려
                        dist = np.sqrt((current_point[0] - point[0]) ** 2 + (current_point[1] - point[1]) ** 2)
                        if 0 < dist < min_dist:
                            min_dist = dist
                            closest_point = point

                if min_dist < 2.0:  # 가까운 거리 제한
                    return closest_point
                return None
    
            # right_line 확장
            def find_closest_point_right(current_point, points):
                min_dist = float('inf')
                closest_point = None
                for point in points:
                    if (point[0] > 0) & (point[1] < 0):   # x가 양수인 점들만 고려
                        dist = np.sqrt((current_point[0] - point[0]) ** 2 + (current_point[1] - point[1]) ** 2)
                        if 0 < dist < min_dist:
                            min_dist = dist
                            closest_point = point

                if min_dist < 2.0:  # 가까운 거리 제한
                    return closest_point
                return None

            if left_point is not None:
                centroids.remove(left_point)

            if right_point is not None:
                centroids.remove(right_point)

            # left_line 확장
            current_left = left_point
            while current_left is not None and len(centroids) > 1:
                next_left = find_closest_point_left(current_left, centroids)
                if next_left is None:
                    break

                left_line.append([next_left[0], next_left[1]])
                centroids.remove(next_left)  # 리스트에서 사용된 점 제거
                current_left = next_left

            # right_line 확장
            current_right = right_point
            while current_right is not None and len(centroids) > 1:
                next_right = find_closest_point_right(current_right, centroids)
                if next_right is None:
                    break
                right_line.append([next_right[0], next_right[1]])
                centroids.remove(next_right) # 리스트에서 사용된 점 제거
                current_right = next_right

            # Function to interpolate points every 10cm (0.1 meters)
            def interpolate_points(line):
                interpolated_line = []
                for i in range(len(line) - 1):
                    start_point = np.array(line[i])
                    end_point = np.array(line[i + 1])
                    dist = np.linalg.norm(end_point - start_point)
                    num_new_points = int(dist // 0.1)  # Number of new points to add every 10cm
                    interpolated_line.append(start_point.tolist())  # Add the original start point
                    if num_new_points > 0:
                        for j in range(1, num_new_points + 1):
                            new_point = start_point + (end_point - start_point) * (j * 0.1 / dist)
                            interpolated_line.append(new_point.tolist())  # Add interpolated points
                interpolated_line.append(line[-1])  # Add the last point of the line
                return interpolated_line

            # Interpolate points for both left_line and right_line
            if len(left_line) > 1:
                left_line = interpolate_points(left_line)
            if len(right_line) > 1:
                right_line = interpolate_points(right_line)

            # PointCloud 메시지 생성 및 발행
            header = Header()
            header.stamp = rospy.Time.now()
            header.frame_id = "velodyne"
            point_cloud_msg = PointCloud()
            point_cloud_msg.header = header
            point_cloud_left_points = []
            point_cloud_right_points = []
            if len(left_line) > 1:
                point_cloud_left_points = [Point32(p[0], p[1], 0) for p in left_line]
            if len(right_line) > 1:
                point_cloud_right_points = [Point32(p[0], p[1], 0) for p in right_line]
            point_cloud_msg.points = point_cloud_left_points + point_cloud_right_points
            self.track_line_pub.publish(point_cloud_msg)
            
            # MarkerArray로 시각화
            marker_array = MarkerArray()
            marker_id = 0
            delete_marker = Marker()
            delete_marker.action = Marker.DELETEALL
            marker_array.markers.append(delete_marker)

            def create_marker(points, color, marker_id):
                if len(points) > 0:
                    tf_point = []
                    tf_point = self.tf2tm(points, self.pose[0], self.pose[1], self.heading)
                    print(self.pose)
                    for point in tf_point:
                        # print("=====================")
                        # print(point)
                        marker = Marker()
                        marker.header.frame_id = "velodyne"
                        marker.type = Marker.SPHERE
                        marker.action = Marker.ADD
                        marker.pose.position.x = point[0] - self.pose[0]
                        marker.pose.position.y = point[1] - self.pose[1]
                        marker.pose.position.z = 0
                        marker.scale.x = 0.2  # 포인트 크기
                        marker.scale.y = 0.2
                        marker.scale.z = 0.2
                        marker.color.r = color[0]
                        marker.color.g = color[1]
                        marker.color.b = color[2]
                        marker.color.a = 1.0
                        marker.id = marker_id
                        marker_id += 1  
                        marker_array.markers.append(marker)
                        # print("================================")
                        # print(point)
                    return marker_id

            if len(left_line) > 1:
                marker_id = create_marker(left_line, (1.0, 1.0, 0.0), marker_id)
            if len(right_line) > 1:
                marker_id = create_marker(right_line, (0.0, 0.0, 1.0), marker_id)

            self.marker_array_pub.publish(marker_array)

    

if __name__ == '__main__':
    try:
        mission_tracking = MissionTracking()
        rate = rospy.Rate(10)  # 10 Hz

        while not rospy.is_shutdown():
            rate.sleep()
    except rospy.ROSInterruptException:
        pass

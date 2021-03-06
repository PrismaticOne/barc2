#!/usr/bin/env python

# Author: Tony Zheng
# ME 131 Lab 7

import rospy
import time
import roslib
import sys
import cv2
import controlpy
import scipy.linalg
import numpy as np
from geometry_msgs.msg import Twist
from std_msgs.msg import String, Int32, Float32, Float32MultiArray, Bool
from sensor_msgs.msg import Image, CompressedImage
from math import sqrt, atan, pi, pow, cos, sin, asin, tan, atan2
from barc.msg import barc_state,ECU, Input, Moving
from controlpy import analysis

# state estimation node
class image_processing_node():
    def __init__(self):    
        
        self.vid = cv2.VideoCapture("/dev/video6")
        self.vid.set(12,5) #contrast
        self.vid.set(13,255) #saturation

        # Calibration Matrices
        self.mtx = np.array([[592.156892, 0.000000, 326.689246], [0.000000, 584.923917, 282.822026], [0.000000, 0.000000, 1.000000]])
        self.dist = np.array([-0.585868, 0.248490, -0.023236, -0.002907, 0.000000])
        self.rel,self.dst = self.vid.read() 
        # Camera resolution
        self.w = 640
        self.h = 480

        # Reference velocity
        self.v_ref = 0.7	
        self.furthestpoint = 1 #ft

        # Number of moving average points
        self.sx = 10
        self.movmean = np.zeros([2,self.sx])

        # Set node rate
        self.loop_rate   = 30
        self.ts          = 1.0 / self.loop_rate
        self.rate        = rospy.Rate(self.loop_rate)
        self.t0          = time.time()

        self.dt = self.ts
        self.count = 0
        self.incount = 0 
        self.total = 0 
        self.avg = 0 
        self.total2 = 0 
        self.avg2 = 0 
        self.publish_image = False;
        self.timeprev = time.time()-self.dt
        time.sleep(0.5)

        # Compute the udistortion and rectification transformation map
        self.newcameramtx, self.roi = cv2.getOptimalNewCameraMatrix(self.mtx,self.dist,(self.w,self.h),0,(self.w,self.h))
        self.mapx,self.mapy = cv2.initUndistortRectifyMap(self.mtx,self.dist,None,self.newcameramtx,(self.w,self.h),5)


        self.statepoints = ''
        self.printme = True

        self.state_constraints = barc_state()
        self.reference_trajectory = barc_state()

        # Initialize publishers and subscribers
        self.moving_pub = rospy.Publisher("moving", Moving, queue_size=1)
        self.moving_pub.publish(True)
        self.reference_trajectory_pub = rospy.Publisher("reference_trajectory", barc_state, queue_size = 1)
        self.reference_image_pub = rospy.Publisher("image_reference_trajectory", Image, queue_size = 10)
        self.uOpt_pub = rospy.Publisher("uOpt", Input, queue_size=1)
        self.draw_lines_sub = rospy.Subscriber("draw_lines", Bool, self.draw_lines,queue_size=1)
        self.draw_lines_pub = rospy.Publisher("draw_lines", Bool, queue_size=1)
        self.publish_states_sub = rospy.Subscriber("publish_states", Bool, self.publish_states,queue_size=1)
        self.publish_states_pub = rospy.Publisher("publish_states", Bool, queue_size=1)
        self.show_Image_pub = rospy.Publisher("show_Image", Bool, queue_size=1)
        self.show_Image_sub = rospy.Subscriber("show_Image", Bool, self.show_Image,queue_size=1)


        while not rospy.is_shutdown():
            try:
                self.count = self.count +1
                self.rel,self.dst = self.vid.read() # gets the current frame from the camera
                self.dt = time.time() - self.timeprev
                #print(self.dt)
                self.timeprev = time.time()

                self.cv_image = cv2.remap(self.dst,self.mapx,self.mapy,cv2.INTER_LINEAR) #Undistorts the fisheye image to rectangular
                self.x,self.y,self.w,self.h = self.roi
                self.dst = self.dst[self.y:self.y+self.h, self.x:self.x+self.w]      

                # yellow = True makes the edge detection search for a yellow track using HSV. False will use grayscale and search for any edge regardless of color
                yellow = True
                kernel_size = 7
                if yellow:
                    cropped = self.cv_image
                    cropped[0:280,0:640] = 0
                    ########cropped = cv2.GaussianBlur(cropped,(kernel_size,kernel_size),0) #0.017s
                    #cropped = cv2.medianBlur(cropped,kernel_size)

                    self.hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV) #.004 

                    #hsv = cv2.GaussianBlur(hsv,(kernel_size,kernel_size),0)
                    #cv2.imshow('hsv',self.hsv[270:480,:])
                    """
                    # define range of blue color in HSV (B,G,R)
                    lower_red = np.array([0,0,180])
                    upper_red = np.array([130,80,255])

                    lower_white = np.array([0,200,200])
                    upper_white = np.array([80,255,255])

                    # Threshold the HSV image to get only blue colors
                    self.reds = cv2.inRange(self.hsv, lower_red, upper_red)
                    self.whites = cv2.inRange(self.hsv, lower_white, upper_white) #0.03s
                    """

                    # define range of blue color in HSV (B,G,R) edit this
                    lower_red = np.array([0,70,170]) 
                    upper_red = np.array([50,150,255])

                    lower_white = np.array([170,200,170])
                    upper_white = np.array([255,255,255])

                    # Threshold the HSV image to get only blue colors
                    self.reds = cv2.inRange(self.cv_image, lower_red, upper_red)
                    self.whites = cv2.inRange(self.cv_image, lower_white, upper_white) #0.03s
                    self.edges = cv2.bitwise_or(self.reds,self.whites)
                    #self.edges = cv2.cvtColor(self.edges, cv2.COLOR_BGR2GRAY)
                    #cv2.imshow("hsv to gray",self.edges)
                    #cv2.imshow("self.edges",self.edges[270:480,:])
                    self.edges = cv2.GaussianBlur(self.edges,(kernel_size,kernel_size),0)
                    #self.edges = cv2.Canny(self.edges,10,200)
                    #######cv2.imshow("self.edges2",self.edges[270:480,:])
                else:
                    # Convert Color Image to Grayscale
                    gray_image = cv2.cvtColor(self.cv_image, cv2.COLOR_BGR2GRAY)
                    gray_image[0:270,0:640] = 0
                    gray_image = cv2.GaussianBlur(gray_image, (kernel_size, kernel_size), 0)
                    #cv2.imshow("blurred Image", gray_image)
                    #in MPC lab, 13 15 100
                    self.edges = cv2.Canny(gray_image,40,80)
                    ######cv2.imshow("Advanced Lane Detection ed", self.edges[270:480,:])
                   # whitecount = cv2.countNonZero(self.edges)

                #print(time.time() - self.timeprev)
                alpha = .6
                beta = 1.
                gamma = 0

                # Colored = True makes the path show up on top of the colored image. 
                colored = False
                if colored:
                    self.line_img_color = np.zeros(self.cv_image.shape, dtype=np.uint8)
                    self.LinesDrawn2_color = cv2.addWeighted(self.cv_image,alpha,self.line_img_color,beta,gamma)
                else: 
                    self.edges_color = cv2.cvtColor(self.edges, cv2.COLOR_GRAY2RGB)
                    self.line_img_color = np.zeros(self.edges_color.shape, dtype=np.uint8)
                    self.LinesDrawn2_color = cv2.addWeighted(self.edges_color,alpha,self.line_img_color,beta,gamma)

                #midpointlist,leftlist,rightlist = self.draw_lines(self.line_img_color,self.edges)
                self.edge_inloop = self.edges
                if self.count>100:
                    self.draw_lines_pub.publish(True)

                fontFace = cv2.FONT_HERSHEY_TRIPLEX
                #self.publish_states(midpointlist,leftlist,rightlist)
                
                if self.publish_image:
                    try:
                        self.reference_image_pub.publish(self.bridge.cv2_to_imgmsg(self.LinesDrawn2_color, "bgr8"))
                        #self.cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
                    except:# CvBridgeError as e:
                        pass#print(e)

                if (self.count <100 and self.count%50==0):
                    self.incount +=1
                    self.timenext = time.time()
                    self.timeElapsed = self.timenext - self.timeprev
                    self.total2 = self.total2+self.timeElapsed
                    self.avg2 = self.total2/(self.incount)
                    print('Average Time: ',self.avg2)

                # Waitkey is necesarry to update image
                ######cv2.waitKey(3)
     
                self.rate.sleep()
            except IOError, (ErrorNumber, ErrorMessage):
                print('HERE')
                print('HERE')
                print(ErrorMessage)
                pass

    #################################################################################
    def show_Image(self,data):
        #cv2.imshow("Advanced Lane Detection ed", self.edges[270:480,:])
        cv2.imshow('cv_image',self.cv_image[270:480,:])
        #cv2.imshow('hsv',self.hsv[270:480,:])
        cv2.imshow("Advanced Lane Detection", self.LinesDrawn2_color[270:480,:])
        cv2.waitKey(3)

    #################################################################################
    def find_offset_in_lane(self,img,x,y,width):
        """
        Finds the edge of the track by searching starting from the center of the image and towards the edge along that row of pixels. Also removes some noise with a custom filter
        """
        leftempty = True;
        rightempty = True;
        y_left = y
        y_right = y
        boxsize = 19
        #print(y)
        #print("here")
        #timehere = time.time()
        while leftempty:
            xleftarray = np.arange(x)
            if xleftarray.any()>480:
                print('ERROR%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
                print(xleftarray)
                print('')
            x_left_index = np.where(img[y_left,xleftarray]>0)
            try:
                i = -1
                while leftempty:
                    x_left = xleftarray[x_left_index[0][i]]
                    leftbound = x_left-boxsize
                    if leftbound <0:
                        leftbound=0
                    
                    Top = img[y_left-boxsize,np.arange(leftbound,x_left+boxsize)]
                    Bottom = img[y_left+boxsize,np.arange(leftbound,x_left+boxsize)]
                    Right = img[np.arange(y_left-boxsize,y_left+boxsize),x_left+boxsize]
                    Left = img[np.arange(y_left-boxsize,y_left+boxsize),leftbound]
                    if (all(Top==0) and all(Bottom==0) and all(Right==0) and all(Left==0)):
                        i-=1
                    else:
                        leftempty = False;
            except:
                x_left = 0
                leftempty = False;
        while rightempty:
            xrightarray = np.arange(x,width)
            x_right_index = np.where(img[y_right,xrightarray]>0)
            try:
                i = 0
                while rightempty:
                    x_right = xrightarray[x_right_index[0][i]]
                    rightbound = x_right+boxsize
                    if rightbound >640:
                        rightbound=640
                    Top = img[y_right-boxsize,np.arange(x_right-boxsize,rightbound)]
                    Bottom = img[y_right+boxsize,np.arange(x_right-boxsize,rightbound)]
                    Right = img[np.arange(y_right-boxsize,y_right+boxsize),rightbound]
                    Left = img[np.arange(y_right-boxsize,y_right+boxsize),x_right-10]
                    if (all(Top==0) and all(Bottom==0) and all(Right==0) and all(Left==0)):
                        i+=1
                    else:
                        rightempty = False;
            except:
                x_right = 640
                rightempty = False;
                #y_right = y_right-5
        #p = input("sss")
        #print(time.time()-timehere)
        return (x_left, x_right,y_left,y_right)
    ##############################################################################################
    def draw_lines(self,data):
        thickness=3
        color=[0, 0,255 ]
        img = self.line_img_color
        self.edges = self.edge_inloop
        height, width = self.edges.shape 
        index_x = (width)//2        
        offset = 0
        previous_x = index_x


        y_newPixel_min = 20 # Where to start the reference trajectory
        y_newPixel_max = 171 # Where to end the reference trajectory

        previous_y = height-y_newPixel_min
        endtrack = False

        # Number of steps k to evenly divide the space from y_newPixel_min to y_newPixel_max
        numpoints = 10
        interval = (y_newPixel_max-y_newPixel_min)//numpoints
        self.stopmoving = False
        converge_limit = 100
        i=0
        dt = self.avg2#self.dt
        
        forward_offset = 1.2 #My forward offset is 1.2 feet because I took my camera points with reference to the center of mass of the car

        for k in xrange(1,numpoints+1,1):
            xIforward = (self.v_ref*dt*k)/0.3048+forward_offset
            y_base = int(self.calc_x_Inertial_to_y_newPixel(xIforward))

            #y_base in xrange(y_newPixel_min,y_newPixel_max,interval):
            #y_base = 150 #20 # this represents 3" in front of the car
            index_y = height - y_base 
            index_x = previous_x
            #print(k)
            #print(xIforward)
            #print(y_base)
            #print(self.edges)
            #print(index_x)
            #print(index_y)
            #print('')

            x_left, x_right,y_left,y_right = self.find_offset_in_lane(self.edges, index_x, index_y, width)
            
            #print(x_left)
            #print(x_right)
            #print(y_left)
            #print(y_right)
            #print('')
            if (not(k==1)and (x_right-x_left)<converge_limit):
                x_left =[-1][0]
                x_right = rightpts[-1][0]
                y_left = leftpts[-1][1]
                y_right = rightpts[-1][1]
                self.stopmoving = True
            if self.stopmoving:
                x_left = leftpts[-1][0]
                x_right = rightpts[-1][0]
                y_left = leftpts[-1][1]
                y_right = rightpts[-1][1]
            midpointx = (x_right + x_left)//2
            #print(midpointx)
            #print(x_right)
            midpointy = (y_right + y_left)//2
            midpts = np.array([(midpointx,midpointy)],dtype = np.int32)
            leftpts = np.array([(x_left,y_left)],dtype = np.int32)
            rightpts = np.array([(x_right,y_right)],dtype = np.int32)
            #print(midpts)
            if (k==1):
                midpointlist = midpts
                leftlist = leftpts
                rightlist = rightpts
            else:
                midpointlist = np.concatenate((midpointlist,midpts))
                leftlist = np.concatenate((leftlist,leftpts))
                rightlist = np.concatenate((rightlist,rightpts))
            if (not(k==1)): 
                cv2.line(self.LinesDrawn2_color, (midpointx, midpointy),(previous_x, previous_y), (0,255,255),3)
            cv2.circle(self.LinesDrawn2_color, (x_right,y_right), 4, (0,255,255), -1)
            cv2.circle(self.LinesDrawn2_color, (x_left,  y_left), 4, (0,255,255), -1)
            cv2.circle(self.LinesDrawn2_color, (midpointx,  midpointy), 3, (0,255,255), -1)
            previous_x = midpointx
            previous_y = midpointy
            # if self.statepoints:
            #     #print(statepoints)
            #     if (self.statepoints[1][i]>480):
            #         self.statepoints[1][i] = 480
            #     if ((i>0) and self.count > 10):
            #         previous_statex = self.statepoints[0][i-1]
            #         previous_statey = self.statepoints[1][i-1]
            #         cv2.line(img, (self.statepoints[0][i], self.statepoints[1][i]),(previous_statex, previous_statey), (0, 255,0),3)
            #     cv2.circle(img, (self.statepoints[0][i],self.statepoints[1][i]), 4, (0, 255,0), -1)
            if endtrack:
                break
            i+=1
        self.midpointlist_inloop = midpointlist
        self.leftlist_inloop = leftlist
        self.rightlist_inloop = rightlist
        self.show_Image_pub.publish(True)
        self.publish_states_pub.publish(True)

    def publish_states(self,data):
        midpointlist = self.midpointlist_inloop 
        leftlist = self.leftlist_inloop
        rightlist =  self.rightlist_inloop

        midpointlist[:,0] = midpointlist[:,0]-320 # Convert x_pixel to x_newpixel
        midpointlist[:,1] = 480-midpointlist[:,1] # Convert y_pixel to y_newpixel
        if ((self.count == 5) and self.printme): 
            print("\nReference Trajectory")
            print(midpointlist)

        midlist_x_Inertial,midlist_y_Inertial = self.convertPixelsToDistance(midpointlist)
        self.reference_trajectory.x = midlist_x_Inertial.tolist()
        self.reference_trajectory.y = midlist_y_Inertial.tolist()
        #print(self.reference_trajectory.x)
        if (midlist_x_Inertial[-1] <self.furthestpoint*.3048):
            self.moving_pub.publish(False)
        else:
            self.moving_pub.publish(True)
        #midlistpsi = np.empty(len(midlist_y_Inertial))
        #self.reference_trajectory.psi = midlistpsi.tolist()
        if ((self.count == 5) and self.printme):
            print(self.reference_trajectory)
        
        self.reference_trajectory_pub.publish(self.reference_trajectory)
        ####################################################################
        # Uncomment this next line when you are ready to use LQR
        self.compute_uOpt(self.reference_trajectory.x,self.reference_trajectory.y,self.v_ref)
        ####################################################################
     ######################################################################################

    def convertPixelsToDistance(self,inputarray):
        #print(inputarray)
        #print("\n\n")
        x_newPixel_list = inputarray[:,0]
        y_newPixel_list = inputarray[:,1]
        transformed_y_Inertial_list = np.float32(x_newPixel_list)
        transformed_x_Inertial_list = np.float32(y_newPixel_list)
        
        for i in np.arange(len(x_newPixel_list)):
            x = x_newPixel_list[i]
            y = y_newPixel_list[i]
           
            transformed_y_Inertial_list[i] = self.calc_x_newPixel_to_y_Inertial(x,y) #number of xpixels from center divided by xpixels per foot
            transformed_x_Inertial_list[i] = self.calc_y_newPixel_to_x_Inertial(y)
        return transformed_x_Inertial_list,transformed_y_Inertial_list

    def calc_x_newPixel_to_y_Inertial(self,x_newPixel,y_newPixel):
        # Transforms the xnewpixel into yinertial frame
        #y_Inertial = -x_newPixel/(-1.5*y_newPixel+342) 
        x_Inertial = self.calc_y_newPixel_to_x_Inertial(y_newPixel)/0.3048
        y_Inertial = (x_newPixel-self.f2(x_Inertial))/self.b_eq(x_Inertial)
        y_newPixelskewed = self.f1(y_Inertial)
        x_Inertial = self.calc_y_newPixel_to_x_Inertial(y_newPixel-y_newPixelskewed)
        y_Inertial = (x_newPixel-self.f2(x_Inertial))/self.b_eq(x_Inertial)

        y_Inertial=y_Inertial*0.3048 #convert ft to m
        return -y_Inertial

    def f1(self,y_Inertial):
        m1 = 0.0555129268626325*pow(y_Inertial,3)-1.16853966634662*pow(y_Inertial,2)+2.61012318593800*y_Inertial-0.193210253120572
        return m1

    def f2(self,x_Inertial):
        m2 = (-0.191666666666620*pow(x_Inertial,3)+2.17499999999949*pow(x_Inertial,2)-7.88333333333155*x_Inertial-14.4000000000019)
        return m2

    def b_eq(self,x_Inertial):
        b = (-2.79999999999994*pow(x_Inertial,3)+39.9999999999993*pow(x_Inertial,2)-208.199999999998*x_Inertial+471.999999999997)
        return b

    def calc_y_newPixel_to_x_Inertial(self,y_newPixel):
        # Transforms the ynewpixel into xinertial frame
        #x_Inertial = 1.04693521412328e-10*pow(y_newPixel,5)-4.04703090338910e-08*pow(y_newPixel,4)+5.58697632038841e-06*pow(y_newPixel,3)-0.000306408741052082*pow(y_newPixel,2)+ 0.0144947520313244*y_newPixel+ 0.472937470305450
        x_Inertial =  6.41114537402027e-09*pow(y_newPixel,4)-1.98328350334255e-06*pow(y_newPixel,3)+0.000217407985767537*pow(y_newPixel,2)-0.00187086071966570*y_newPixel+1.20129636574706
        x_Inertial=x_Inertial*0.3048 #convert ft to m
        return x_Inertial

    def calc_x_Inertial_to_y_newPixel(self,x_Inertial):
        # Transforms the ynewpixel into xinertial frame
        y_newPixel = -2.21264430779643*pow(x_Inertial,4)+  35.1296969153215*pow(x_Inertial,3) -211.245402739726*pow(x_Inertial,2)+   589.932691380840*x_Inertial   -460.079758159785
        return y_newPixel
    #########################################################################
    def compute_uOpt(self,x_ref,y_ref,v_ref):
        try:
            if not(self.stopmoving):
                """
                READ MEEEEEEE #############################################
                j = the first point you look at for the reference trajectory (for radius calculation) so j = 2 for example, you look at the 3rd closest point 
                interval = the number that is added to j for the subsequent point (for radius calculation). So if j = 2, interval = 4.... the points we observe are the 3rd, 7th and 11th

                Play around with this values to adjust how far you look ahead to calculate the next optimal input. (Recall there is some time delay so you may want to send an input from the future)
                """
                dt = self.avg2#self.dt
                lr = 0.15
                lf = 0.15
                j = 3
                interval = 2
                x_ref_for_radius = [x_ref[j+interval],x_ref[j+interval*2]]
                y_ref_for_radius = [y_ref[j+interval],y_ref[j+interval*2]]
                x_ref_for_radius = np.append(x_ref[j],x_ref_for_radius)
                y_ref_for_radius = np.append(y_ref[j],y_ref_for_radius);

                x1 = x_ref_for_radius[0];
                x2 = x_ref_for_radius[1];
                x3 = x_ref_for_radius[2];
                y1 = y_ref_for_radius[0];
                y2 = y_ref_for_radius[1];
                y3 = y_ref_for_radius[2];
                ma = (y2-y1)/(x2-x1);
                mb = (y3-y2)/(x3-x2);
                if ((abs(y2-y1<1e-5))or(abs(y3-y2<1e-5))):
                    y2 = y2 + 1e-3;
                    ma = (y2-y1)/(x2-x1);
                    mb = (y3-y2)/(x3-x2);
                x_c = (ma*mb*(y1-y3)+mb*(x1+x2)-ma*(x2+x3))/(2*(mb-ma));
                y_c = (-1/ma)*(x_c-(x1+x2)/2)+(y1+y2)/2;
                Radius = sqrt(pow((x2-x_c),2)+pow((y2-y_c),2));
                psidot_des = v_ref/Radius;
                if Radius<lr:
                    Radius = lr*2
                if y_c>0:
                    beta_des = abs(asin(lr/Radius))*-1;
                    psi_des = psidot_des*dt;
                else:
                    beta_des = abs(asin(lr/Radius));
                    psi_des = psidot_des*dt*-1;
                """
                print('')
                print(self.count)
                print('Radius',Radius)
                print('beta_des',beta_des)
                print('psi_des',psi_des*180/pi)
                """

                Ac = np.matrix([[0, 0, -v_ref*sin(psi_des+beta_des)],[0, 0, v_ref*cos(psi_des+beta_des)],[0, 0, 0]]);
                Bc = np.matrix([[cos(psi_des+beta_des), -v_ref*sin(psi_des+beta_des)],[sin(psi_des+beta_des), v_ref*cos(psi_des+beta_des)],[sin(beta_des)/lr, v_ref*cos(beta_des)/lr]])

                Q = np.matrix([[50, 0, 0],[0, 50, 0],[0, 0, 1]]);
                R = np.matrix([[25, 0 ],[0, 1]]);

                if j == 0:
                    z = np.matrix([[0],[0],[0]])
                else:
                    z = np.matrix([[x_ref[j-1]],[y_ref[j-1]],[0]])
                z_ref = [[x_ref[0]],[y_ref[0]],[psi_des]];
                u_bar = [[v_ref],[beta_des]];

                # Compute the LQR controller
                K, X, closedLoopEigVals = controlpy.synthesis.controller_lqr_discrete_from_continuous_time(Ac, Bc, Q, R, dt)

                u_Opt = -K*(z-z_ref)+u_bar;
                vOpt = u_Opt[0,0]
                betaOpt = u_Opt[1,0]
                deltaOpt = atan2(((lf+lr)*tan(u_Opt[1,0])),lr)


                znext = z + self.dt*np.matrix([[vOpt*cos(z[2]+betaOpt)],[vOpt*sin(z[2]+betaOpt)],[vOpt*sin(betaOpt)/lr]])
                # Moving Average
                if (self.count>self.sx):
                    self.movmean = np.delete(self.movmean,0,1)
                    self.movmean = np.append(self.movmean,np.array([[vOpt],[deltaOpt]]),axis=1)
                    #print(self.movmean)
                    #print(np.mean(self.movmean,axis=1))
                    vOpt = np.mean(self.movmean,axis=1)[0]
                    deltaOpt = np.mean(self.movmean,axis=1)[1]

                """
                print('z_ref ',z_ref)
                print('x_c ',x_c)
                print('y_c ',y_c)
                print('znext ',znext)
                print('beta_des ',beta_des)
                """
                """
                print('betaOpt ',betaOpt)
                print('vopt ',vOpt)
                print('deltaOpt ',deltaOpt)
                print('--------------------------------------')
                """
                """
                #print(u_Opt[0,0])
                #print(u_Opt[1,0]*180/pi)
                #print('')
                # print(K)
                """
                self.uOpt_pub.publish(vOpt,deltaOpt)
        #except ValueError:# IOError, (ErrorNumber, ErrorMessage):
        except IOError,(ErrorNumber, ErrorMessage):
            print('jere')
            print(ErrorMessage)
            #pass

def shutdown_func():
    cv2.destroyAllWindows()

def main(args):
    rospy.on_shutdown(shutdown_func)
    global image_processor_global
    global offset_global

    # Intialize the node
    rospy.init_node('image_processing_node', anonymous=True)

    image_processor_global = image_processing_node()

    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down")
    cv2.destroyAllWindows()

if __name__ == '__main__':
    try:
        main(sys.argv)
    except rospy.ROSInterruptException:
        pass

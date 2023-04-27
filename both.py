import sys
import cv2
import numpy as np
import pickle
from tracker import tracker
from moviepy.editor import VideoFileClip

# Object detection
# Load class names
classNames = []
classFile = 'coco.names'
with open(classFile, 'rt') as f:
    classNames = f.read().rstrip('\n').split('\n')

# Load model
configPath = 'ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt'
weightsPath = 'frozen_inference_graph.pb'
net = cv2.dnn_DetectionModel(weightsPath, configPath)
net.setInputSize(320, 320)
net.setInputScale(1.0 / 127.5)
net.setInputMean((127.5, 127.5, 127.5))
net.setInputSwapRB(True)

# Set threshold to detect objects
thres = 0.45

# Focal length of camera (in mm)
focalLength = 10

# Define the background color
bg_color = (100, 100, 100)



# Lane detection
dist_pickle = pickle.load(open("calibration_pickle.p", "rb"))
mtx = dist_pickle["mtx"]
dist = dist_pickle["dist"]
processed_frames = []


# Functions for lane detection
# ... (same as the previous code, starting from "def abs_sobel_thresh(img, orient='x', sobel_kernel=3, thresh=(0,255)):")
def abs_sobel_thresh(img, orient='x', sobel_kernel=3, thresh=(0,255)):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if orient == 'x':
        abs_sobel = np.absolute(cv2.Sobel(gray, cv2.CV_64F, 1, 0))
    if orient == 'y':
        abs_sobel = np.absolute(cv2.Sobel(gray, cv2.CV_64F, 0, 1))
    
    scaled_sobel = np.uint8(255*abs_sobel/np.max(abs_sobel))
    binary_output = np.zeros_like(scaled_sobel)
    
    binary_output[(scaled_sobel >= thresh[0]) & (scaled_sobel <= thresh[1])] = 1
    return binary_output

def mag_thresh(img, sobel_kernel=3, mag_thresh=(0,255)):
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=sobel_kernel)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=sobel_kernel)
    
    gradmag = np.sqrt(sobelx**2+sobely**2)
    scale_factor = np.max(gradmag)/255
    gradmag = (gradmag/scale_factor).astype(np.uint8)
    
    binary_output = np.zeros_like(gradmag)
    binary_output[(gradmag >= mag_thresh[0]) & (gradmag <= mag_thresh[1])] = 1
    return binary_output
    
def dir_threshold(image, sobel_kernel=3, thresh=(0, np.pi/2)):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=sobel_kernel)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=sobel_kernel)
    
    with np.errstate(divide='ignore', invalid='ignore'):
        absgraddir = np.absolute(np.arctan(sobely/sobelx))
        binary_output = np.zeros_like(absgraddir)
        binary_output[(absgraddir >= thresh[0]) & (absgraddir <= thresh[1])] = 1
    return binary_output

def color_threshold(image, sthresh=(0,255), vthresh=(0,255), lthresh=(0,255)):
    hls = cv2.cvtColor(image, cv2.COLOR_RGB2HLS)
    s_channel = hls[:,:,2]
    s_binary = np.zeros_like(s_channel)
    s_binary[(s_channel >= sthresh[0]) & (s_channel <= sthresh[1])] = 1

    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    v_channel = hsv[:,:,2]
    v_binary = np.zeros_like(v_channel)
    v_binary[(v_channel >= vthresh[0]) & (v_channel <= vthresh[1])] = 1

    output = np.zeros_like(s_channel)
    output[(s_binary == 1) & (v_binary == 1)] = 1
    return output
    
def window_mask(width, height, img_ref, center, level):
    output = np.zeros_like(img_ref)
    output[int(img_ref.shape[0] - (level + 1) * height):int(img_ref.shape[0] - level * height),
    max(0, int(center - width / 2)):min(int(center + width / 2), img_ref.shape[1])] = 1
    return output

def draw_thumbnails(img_cp, img, window_list, thumb_w=100, thumb_h=80, off_x=30, off_y=30):

    for i, bbox in enumerate(window_list):
        thumbnail = img[bbox[0][1]:bbox[1][1], bbox[0][0]:bbox[1][0]]
        vehicle_thumb = cv2.resize(thumbnail, dsize=(thumb_w, thumb_h))
        start_x = 300 + (i+1) * off_x + i * thumb_w
        img_cp[off_y + 30:off_y + thumb_h + 30, start_x:start_x + thumb_w, :] = vehicle_thumb




def process_image(img):
    # Lane detection
    # ... (same as the previous code, starting from "img = cv2.undistort(img, mtx, dist, None, mtx)")

    img = cv2.undistort(img, mtx, dist, None, mtx)

    preprocessImage = np.zeros_like(img[:,:,0])
    gradx = abs_sobel_thresh(img, orient='x', thresh=(12,255))
    grady = abs_sobel_thresh(img, orient='x', thresh=(25,255))
    c_binary = color_threshold(img, sthresh=(100,255),vthresh=(50,255))
    preprocessImage[((gradx==1)&(grady==1)|(c_binary==1))] = 255

    img_size = (img.shape[1], img.shape[0])
    bot_width = .75 #changed from .76
    mid_width = .1 #changed this value - seemed to work a lot better than 0.08 
    height_pct = .62
    bottom_trim = .935
    src = np.float32([[img.shape[1]*(.5-mid_width/2),img.shape[0]*height_pct],[img.shape[1]*(.5+mid_width/2),img.shape[0]*height_pct],
                      [img.shape[1]*(.5+bot_width/2),img.shape[0]*bottom_trim],[img.shape[1]*(.5-bot_width/2),img.shape[0]*bottom_trim]])
    offset = img_size[0]*.25
    dst = np.float32([[offset, 0], [img_size[0]-offset, 0],[img_size[0]-offset, img_size[1]],[offset, img_size[1]]])

    M = cv2.getPerspectiveTransform(src, dst) 
    Minv = cv2.getPerspectiveTransform(dst, src)
    warped = cv2.warpPerspective(preprocessImage, M, img_size,flags=cv2.INTER_LINEAR)

    window_width = 25
    window_height = 80
    curve_centers = tracker(Mywindow_width=window_width,Mywindow_height=window_height,Mymargin=25,My_ym=10/720,My_xm=4/384,Mysmooth_factor=15)
    window_centroids = curve_centers.find_window_centroids(warped)

    l_points = np.zeros_like(warped)
    r_points = np.zeros_like(warped)

    rightx = []
    leftx = []

    for level in range(0,len(window_centroids)):
        l_mask = window_mask(window_width,window_height,warped,window_centroids[level][0],level)
        r_mask = window_mask(window_width,window_height,warped,window_centroids[level][1],level)

        leftx.append(window_centroids[level][0]) 
        rightx.append(window_centroids[level][1])

        l_points[(l_points==255)|((l_mask==1))] = 255
        r_points[(r_points==255)|((r_mask==1))] = 255

    template = np.array(r_points+l_points,np.uint8)
    zero_channel = np.zeros_like(template)
    template = np.array(cv2.merge((zero_channel,template,zero_channel)),np.uint8)
    warpage = np.array(cv2.merge((warped,warped,warped)),np.uint8)
    result = cv2.addWeighted(warpage,1,template,0.5,0.0)

    yvals = range(0,warped.shape[0])
    res_yvals = np.arange(warped.shape[0]-(window_height/2),0,-window_height)

    left_fit = np.polyfit(res_yvals,leftx,2)
    left_fitx = left_fit[0]*yvals*yvals + left_fit[1]*yvals + left_fit[2]
    left_fitx = np.array(left_fitx,np.int32)

    right_fit = np.polyfit(res_yvals,rightx,2)
    right_fitx = right_fit[0]*yvals*yvals + right_fit[1]*yvals + right_fit[2]
    right_fitx = np.array(right_fitx,np.int32)

    left_lane = np.array(list(zip(np.concatenate((left_fitx-window_width/2,left_fitx[::-1]+window_width/2),axis=0),np.concatenate((yvals,yvals[::-1]),axis=0))),np.int32)

    right_lane = np.array(list(zip(np.concatenate((right_fitx-window_width/2,right_fitx[::-1]+window_width/2),axis=0),np.concatenate((yvals,yvals[::-1]),axis=0))),np.int32)

    inner_lane = np.array(list(zip(np.concatenate((left_fitx+window_width/2,right_fitx[::-1]+window_width/2),axis=0),np.concatenate((yvals,yvals[::-1]),axis=0))),np.int32)

    road = np.zeros_like(img)
    road_bkg = np.zeros_like(img)
    cv2.fillPoly(road,[left_lane],color=[255,0,0])
    cv2.fillPoly(road,[inner_lane],color=[0,255,0])
    cv2.fillPoly(road,[right_lane],color=[0,0,255])
    cv2.fillPoly(road_bkg,[left_lane],color=[255,255,255])
    cv2.fillPoly(road_bkg,[right_lane],color=[255,255,255])

    road_warped = cv2.warpPerspective(road,Minv,img_size,flags=cv2.INTER_LINEAR)
    road_warped_bkg = cv2.warpPerspective(road_bkg,Minv,img_size,flags=cv2.INTER_LINEAR)

    base = cv2.addWeighted(img, 1.0, road_warped_bkg, -1.0, 0.0)
    result = cv2.addWeighted(base,1.0,road_warped,0.7,0.0)

    #measure pixels in y and x directions
    ym_per_pix = curve_centers.ym_per_pix
    xm_per_pix = curve_centers.xm_per_pix

    curve_fit_cr = np.polyfit(np.array(res_yvals,np.float32)*ym_per_pix,np.array(leftx,np.float32)*xm_per_pix,2)
    curverad = ((1+(2*curve_fit_cr[0]*yvals[-1]*ym_per_pix+curve_fit_cr[1])**2)**1.5)/np.absolute(2*curve_fit_cr[0]) #remember that it's the equation from the lesson (derivatives) - radius of curvature

    camera_center = (left_fitx[-1] + right_fitx[-1])/2
    center_diff = (camera_center-warped.shape[1]/2)*xm_per_pix
    side_pos = 'left'
    if center_diff <= 0:
        side_pos = 'right'
    if center_diff > 0.2:
        turn_direction = 'Turn Right'
    elif center_diff < -0.2:
        turn_direction = 'Turn Left'
    else:
        turn_direction = 'Straight'
        


    # cv2.putText(result,'Radius of curvature = '+str(round(curverad,3))+'(m)',(50,50),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
    # cv2.putText(result,'Vehicle is '+str(abs(round(center_diff,3)))+'m '+side_pos+' of center',(50,100), cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
    # cv2.putText(result, turn_direction, (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    #displaying detected objects

    # Object detection
    classIds, confs, bbox = net.detect(img, confThreshold=thres)

    # Draw bounding box and label for each object detected
    if len(classIds) != 0:
        for classId, confidence, box in zip(classIds.flatten(), confs.flatten(), bbox):
            # Calculate distance of object from camera (in meters)
            distance = round((2 * focalLength) / box[2], 2)
            cv2.rectangle(img, box, color=(0, 255, 0), thickness=3)
            cv2.putText(img, classNames[classId - 1].upper(), (box[0] + 10, box[1] + 30),
                        cv2.FONT_HERSHEY_COMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(img, str(distance) + " m", (box[0] + 200, box[1] + 30),
                        cv2.FONT_HERSHEY_COMPLEX, 1, (0, 255, 0), 2)

    # Get the width of the image
    img_width = result.shape[1]

    

    # Draw a filled rectangle as the background
    cv2.rectangle(result, (0, 0), (img_width, 150), bg_color, -1)

    # Define the list of detected objects and their confidence levels
    # detected_objects = [('car', 0.85), ('person', 0.75), ('bike', 0.65)]

    # Format the detected objects string
    # objects_string = 'Detected objects: '
    # for obj, conf in detected_objects:
    #     objects_string += f'{obj} ({conf:.2f}), '
    # objects_string = objects_string[:-2]


    # Add the text on top of the background
    cv2.putText(result, 'Lane Status', (100, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
    #radius of curvature
    cv2.putText(result, 'Radius of curvature = '+str(round(curverad,3))+'(m)', (50, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    #vehicle position
    cv2.putText(result, 'Vehicle Position: '+str(abs(round(center_diff,3)))+'m '+side_pos+' of center', (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    # Assistance
    cv2.putText(result, 'Assistance:'+ ' '+turn_direction, (50, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    # detected objects
    cv2.putText(result, 'Detected Objects', (800, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

    

    # cv2.putText(result, objects_string, (800, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)


    


    # # Display final result
    # cv2.putText(result,'Lane Status',(100,50),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,0),2)
    # cv2.putText(result,'Radius of curvature = '+str(round(curverad,3))+'(m)',(50,75),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,0),1)
    # cv2.putText(result,'Vehicle Position: '+str(abs(round(center_diff,3)))+'m '+side_pos+' of center',(50,100), cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,0,0),1)
    # cv2.putText(result, 'Assistance:'+ ' '+turn_direction, (50, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)




    final_result = cv2.addWeighted(result, 1, img, 0.5, 0)
    return final_result


# For video clip or real-time
cap = cv2.VideoCapture('project_video.mp4')
#output video
fourcc = cv2.VideoWriter_fourcc(*'mp4v') # codec
out = cv2.VideoWriter('recorded_output.mp4', fourcc, 25, (1280, 720)) # output file name, codec, fps, size of frames

while True:
    success, img = cap.read()
    result = process_image(img)



    out.write(result)

    # Display output image or video
    cv2.imshow("Output", result)

    # Exit on 's' key press
    key = cv2.waitKey(1) & 0xFF
    if key == ord('s'):
        break
    

# Release video capture and close windows
cv2.imshow('Result', result)
cap.release()
out.release()
cv2.destroyAllWindows()

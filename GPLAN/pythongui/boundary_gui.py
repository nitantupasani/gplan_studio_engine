import tkinter as tk 
from tkinter import font
from tkinter import messagebox
def gui_fnc(nodes):
	north_bdy = []
	east_bdy = []
	west_bdy =[]
	south_bdy = []
	root = tk.Toplevel() 

	root.title('Boundary Input')
	root.geometry(str(1000) + 'x' + str(400))
	Upper_right = tk.Label(root, text ="Provide room choice for each boundary",font = ("Times New Roman",12)) 
	  
	Upper_right.place(relx = 0.70,  
					  rely = 0.08, 
					  anchor ='ne')

	room_head = []
	north_bdy_label = tk.Label(root,text = "North Boundary");
	north_bdy_label.place(relx = 0.15,rely = 0.2,anchor ='ne')
	east_bdy_label = tk.Label(root,text = "East Boundary");
	east_bdy_label.place(relx = 0.15,rely = 0.28,anchor ='ne')
	south_bdy_label = tk.Label(root,text = "South Boundary");
	south_bdy_label.place(relx = 0.15,rely = 0.36,anchor ='ne')
	west_bdy_label = tk.Label(root,text = "West Boundary");
	west_bdy_label.place(relx = 0.15,rely = 0.44,anchor ='ne')
	north_east_bdy_label = tk.Label(root,text = "North-East Corner");
	north_east_bdy_label.place(relx = 0.15,rely = 0.52,anchor ='ne')
	south_east_bdy_label = tk.Label(root,text = "South-East Corner");
	south_east_bdy_label.place(relx = 0.15,rely = 0.60,anchor ='ne')
	south_west_bdy_label = tk.Label(root,text = "South-West Corner");
	south_west_bdy_label.place(relx = 0.15,rely = 0.68,anchor ='ne')
	north_west_bdy_label = tk.Label(root,text = "North-West Corner");
	north_west_bdy_label.place(relx = 0.15,rely = 0.76,anchor ='ne')
	north_bdy_rooms=[]
	north_bdy_checkbtns=[]
	east_bdy_rooms=[]
	east_bdy_checkbtns=[]
	south_bdy_rooms=[]
	south_bdy_checkbtns=[]
	west_bdy_rooms=[]
	west_bdy_checkbtns=[]
	north_east_bdy_rooms=[]
	north_east_bdy_checkbtns=[]
	south_east_bdy_rooms=[]
	south_east_bdy_checkbtns=[]
	south_west_bdy_rooms=[]
	south_west_bdy_checkbtns=[]
	north_west_bdy_rooms=[]
	north_west_bdy_checkbtns=[]
	no_constraint = tk.IntVar()
	boundary_constraint = [[],[],[],[]]
	corner_constraint = [[],[],[],[]]
	def isvalid():
		for i in range(0,nodes):
			if(north_bdy_rooms[i].get()!=0 and south_bdy_rooms[i].get()!=0 and east_bdy_rooms[i].get()==0 and west_bdy_rooms[i].get()==0):
				return False
			if(east_bdy_rooms[i].get()!=0 and west_bdy_rooms[i].get()!=0 and north_bdy_rooms[i].get()==0 and south_bdy_rooms[i].get()==0):
				return False
			if(north_bdy_rooms[i].get()!=0 and south_bdy_rooms[i].get()!=0 and east_bdy_rooms[i].get()!=0 and west_bdy_rooms[i].get()!=0):
				return False
		return True

	def isvalid2():
		for i in range(0,nodes):
			if((north_west_bdy_rooms[i].get()!=0 and north_east_bdy_rooms[i].get()!=0 and south_east_bdy_rooms[i].get()!=0)):
				return False
			if((north_west_bdy_rooms[i].get()!=0 and north_east_bdy_rooms[i].get()!=0 and south_west_bdy_rooms[i].get()!=0)):
				return False
			if((north_west_bdy_rooms[i].get()!=0 and south_east_bdy_rooms[i].get()!=0 and south_west_bdy_rooms[i].get()!=0)):
				return False
			if((north_east_bdy_rooms[i].get()!=0 and south_east_bdy_rooms[i].get()!=0 and south_west_bdy_rooms[i].get()!=0)):
				return False
			if((north_west_bdy_rooms[i].get()!=0 and south_east_bdy_rooms[i].get()!=0)):
				return False
			if((north_east_bdy_rooms[i].get()!=0 and south_west_bdy_rooms[i].get()!=0)):
				return False
		set =0
		for i in range(0,nodes):
			if(north_west_bdy_rooms[i].get()!=0):
				if(set==0):
					set=1
				else:
					return False
		set =0
		for i in range(0,nodes):
			if(north_east_bdy_rooms[i].get()!=0):
				if(set==0):
					set=1
				else:
					return False
		set =0
		for i in range(0,nodes):
			if(south_west_bdy_rooms[i].get()!=0):
				if(set==0):
					set=1
				else:
					return False
		set =0
		for i in range(0,nodes):
			if(south_east_bdy_rooms[i].get()!=0):
				if(set==0):
					set=1
				else:
					return False
		return True



	def clicked():
		if(no_constraint.get() == 0):
			for i in range(0,nodes):
				north_bdy_checkbtns[i].config(state="normal")
				east_bdy_checkbtns[i].config(state="normal")
				south_bdy_checkbtns[i].config(state="normal")
				west_bdy_checkbtns[i].config(state="normal")
				north_east_bdy_checkbtns[i].config(state="normal")
				south_east_bdy_checkbtns[i].config(state="normal")
				south_west_bdy_checkbtns[i].config(state="normal")
				north_west_bdy_checkbtns[i].config(state="normal")
				
		else:
			for i in range(0,nodes):
				north_bdy_checkbtns[i].config(state="disabled")
				east_bdy_checkbtns[i].config(state="disabled")
				south_bdy_checkbtns[i].config(state="disabled")
				west_bdy_checkbtns[i].config(state="disabled")
				north_east_bdy_checkbtns[i].config(state="disabled")
				south_east_bdy_checkbtns[i].config(state="disabled")
				south_west_bdy_checkbtns[i].config(state="disabled")
				north_west_bdy_checkbtns[i].config(state="disabled")
	def button_clicked():
		if(isvalid()):
			if(isvalid2()):
				if(no_constraint.get() == 0):
					for i in range(0,nodes):
						if(south_bdy_rooms[i].get()!=0):
							boundary_constraint[0].append(i)
						if(east_bdy_rooms[i].get()!=0):
							boundary_constraint[1].append(i)
						if(north_bdy_rooms[i].get()!=0):
							boundary_constraint[2].append(i)
						if(west_bdy_rooms[i].get()!=0):
							boundary_constraint[3].append(i)
						if(south_east_bdy_rooms[i].get()!=0):
							corner_constraint[0].append(i)
						if(north_east_bdy_rooms[i].get()!=0):
							corner_constraint[1].append(i)
						if(north_west_bdy_rooms[i].get()!=0):
							corner_constraint[2].append(i)
						if(south_west_bdy_rooms[i].get()!=0):
							corner_constraint[3].append(i)
					print(boundary_constraint)
					print(corner_constraint)
					root.destroy()
				else:
					print(boundary_constraint)
					root.destroy()
			else:
				messagebox.showerror("Please make valid selection.","Either one room is chosen for more than two corner or more than one room for one corner.")
		else:
			messagebox.showerror("Please make valid selection.","Either one room is chosen for all boundaries or a room chosen for non-adjacent boundaries.")

	no_constraint_checkbtn = tk.Checkbutton(root,text='No boundary constraint', variable = no_constraint,onvalue = 1, offvalue = 0,command=clicked)
	no_constraint_checkbtn.place(relx = 0.85, rely = 0.9, anchor = 'ne')
	for i in range(0,nodes):
		room_head.append(tk.Label(root,text= "Room "+str(i)))
		room_head[i].place(relx = 0.20 + 0.05*i, rely = 0.15,anchor = 'ne')
		north_bdy_rooms.append(tk.IntVar())
		north_bdy_checkbtns.append(tk.Checkbutton(root, variable = north_bdy_rooms[i],onvalue = 1, offvalue = 0))
		north_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.2, anchor = 'ne')
		east_bdy_rooms.append(tk.IntVar())
		east_bdy_checkbtns.append(tk.Checkbutton(root, variable = east_bdy_rooms[i],onvalue = 1, offvalue = 0))
		east_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.28, anchor = 'ne')
		south_bdy_rooms.append(tk.IntVar())
		south_bdy_checkbtns.append(tk.Checkbutton(root, variable = south_bdy_rooms[i],onvalue = 1, offvalue = 0))
		south_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.36, anchor = 'ne')
		west_bdy_rooms.append(tk.IntVar())
		west_bdy_checkbtns.append(tk.Checkbutton(root, variable = west_bdy_rooms[i],onvalue = 1, offvalue = 0))
		west_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.44, anchor = 'ne')
		north_east_bdy_rooms.append(tk.IntVar())
		north_east_bdy_checkbtns.append(tk.Checkbutton(root, variable = north_east_bdy_rooms[i],onvalue = 1, offvalue = 0))
		north_east_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.52, anchor = 'ne')
		south_east_bdy_rooms.append(tk.IntVar())
		south_east_bdy_checkbtns.append(tk.Checkbutton(root, variable = south_east_bdy_rooms[i],onvalue = 1, offvalue = 0))
		south_east_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.60, anchor = 'ne')
		south_west_bdy_rooms.append(tk.IntVar())
		south_west_bdy_checkbtns.append(tk.Checkbutton(root, variable = south_west_bdy_rooms[i],onvalue = 1, offvalue = 0))
		south_west_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.68, anchor = 'ne')
		north_west_bdy_rooms.append(tk.IntVar())
		north_west_bdy_checkbtns.append(tk.Checkbutton(root, variable = north_west_bdy_rooms[i],onvalue = 1, offvalue = 0))
		north_west_bdy_checkbtns[i].place(relx = 0.20+0.05*i, rely = 0.76, anchor = 'ne')
	button = tk.Button(root, text='Submit', padx=5, command=button_clicked)      
	button.place(relx = 0.5,  
					  rely = 0.9, 
					  anchor ='ne')
	root.wait_window(root)
	return boundary_constraint,corner_constraint

	# for i in range(0,nodes):
	# 	i_value_x = int(i/10)
	# 	i_value_y = i%10
	# 	w.append(tk.IntVar(None))
	# 	w1.append(tk.IntVar(None)) 
	# 	minA.append(tk.IntVar(None)) 
	# 	maxA.append(tk.IntVar(None)) 
	# 	if(i_value_y == 0):
	# 		text_head_width.append("text_head_width_"+str(i_value_x+1))
	# 		text_head_width[i_value_x] = tk.Label(root,text = "Min Width")
	# 		text_head_width[i_value_x].place(relx = 0.30 + 0.20*i_value_x,  
	# 				  rely = 0.2, 
	# 				  anchor ='ne')
	# 		text_head_width1.append("text_head_width1_"+str(i_value_x+1))
	# 		text_head_width1[i_value_x] = tk.Label(root,text = "Max Width")
	# 		text_head_width1[i_value_x].place(relx = 0.40 + 0.20*i_value_x,  
	# 				  rely = 0.2, 
	# 				  anchor ='ne')
	# 		text_head_area.append("text_head_area_"+str(i_value_x+1))
	# 		text_head_area[i_value_x] = tk.Label(root,text = "Min Area")
	# 		text_head_area[i_value_x].place(relx = 0.50 + 0.20*i_value_x,  
	# 				  rely = 0.2, 
	# 				  anchor ='ne')
	# 		text_head_area1.append("text_head_area1_"+str(i_value_x+1))
	# 		text_head_area1[i_value_x] = tk.Label(root,text = "Max Area")
	# 		text_head_area1[i_value_x].place(relx = 0.60 + 0.20*i_value_x,  
	# 				  rely = 0.2, 
	# 				  anchor ='ne')
	# 	text_room.append("text_room_"+str(i))
	# 	text_room[i] = tk.Label(root, text ="Room"+str(i),font = ("Times New Roman",8)) 

	# 	text_room[i].place(relx = 0.20 + 0.20*i_value_x,  
	# 				  rely = 0.3 + (0.05 * i_value_y), 
	# 				  anchor ='ne')
	# 	value_width.append("value_width" + str(i))
	# 	value_width[i] = tk.Entry(root, width = 5,textvariable=w[i])
	# 	value_width[i].place(relx = 0.30 +0.20*i_value_x,  
	# 				  rely = 0.3 +(0.05)*i_value_y, 
	# 				  anchor ='ne')
	# 	value_width1.append("value_width1" + str(i))
	# 	value_width1[i] = tk.Entry(root, width = 5,textvariable=w1[i])
	# 	value_width1[i].place(relx = 0.40 +0.20*i_value_x,  
	# 				  rely = 0.3 +(0.05)*i_value_y, 
	# 				  anchor ='ne')
	# 	value_area.append("value_area"+str(i))
	# 	value_area[i] = tk.Entry(root, width = 5,textvariable=minA[i])
	# 	value_area[i].place(relx = 0.50+ 0.20*i_value_x,  
	# 				  rely = 0.3 + (0.05)*i_value_y, 
	# 				   anchor ='ne')
	# 	value_area1.append("value_area1"+str(i))
	# 	value_area1[i] = tk.Entry(root, width = 5,textvariable=maxA[i])
	# 	value_area1[i].place(relx = 0.60+ 0.20*i_value_x,  
	# 				  rely = 0.3 + (0.05)*i_value_y, 
	# 				   anchor ='ne')
	

	

	
	# # checkvar1 = tk.IntVar()
	# # c1 = tk.Checkbutton(root, text = "Default AR Range", variable = checkvar1,onvalue = 1, offvalue = 0,command=clicked)
	# # c1.place(relx = 0.85, rely = 0.9, anchor = 'ne')

	# root.wait_window(root)
	# print(min_width,max_width,min_height,max_height)
	# return min_width,max_width,min_height,max_height
	

if __name__ == "__main__":
	gui_fnc(3)
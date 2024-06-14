"""
Dimensioning Module
This module allows user to obtain optimised dimensions for height and width of each room from their inputs. This module handles symmetry constraints,
aspect ratio constraints as well as plot size constraints.

This module contains the following functions stored in separate files:
    * floorplan_to_st - Takes user inputs and converts them into encoded matrix form of horizontal and vertical st graphs. Calls solve_linear and
    					convert_adj_equ_sym.
	* convert_adj_equ_sym - Converts encoded st graphs into linear equations.
    * solve_linear - Takes few user inputs along with the encoded horizontal and vertical st graphs to give optimized dimensions .

"""
import numpy as np
import scipy.optimize

def solve_linear(f_VER, A_VER, Aeq_VER, Beq_VER, f_HOR, A_HOR, Aeq_HOR, Beq_HOR, min_width, max_width, min_height, max_height, min_ar, max_ar):
	"""
	   Args:
		   f_VER: The coefficients of the linear objective function to be minimized for the width constraints.
		   A_VER: The inequality constraint matrix. Each row of A_VER specifies the coefficients of a linear
				  inequality constraints on widths.
		   Aeq_VER: The equality constraint matrix. Each row of Aeq_VER specifies the coefficients of a
					equality constraint on widths.
		   Beq_VER: The equality constraint vector. Each element of Aeq_VER @ width must equal
					the corresponding element of Beq_VER.
		   f_HOR: The coefficients of the linear objective function to be minimized for the height constraints.
		   A_HOR: The inequality constraint matrix. Each row of A_HOR specifies the coefficients of a linear
				  inequality constraints on heights.
		   Aeq_HOR: The equality constraint matrix. Each row of Aeq_HOR specifies the coefficients of a
					equality constraint on heights.
		   Beq_HOR: The equality constraint vector. Each element of Aeq_HOR @ height must equal
					the corresponding element of Beq_HOR.
		   min_width: List of minimum width constraints of each room
		   min_height: List of minimum height constraints of each room
		   max_width: List of maximum width constraints of each room
		   max_height: List of maximum height constraints of each room
		   min_ar: List of minimum aspect ratio constraints of each room
		   max_ar: List of maximum aspect ratio constraints of each room
	   Attributes:
			b_VER: The inequality constraint vector. Each element represents an upper bound on the corresponding
			 	   value of A_VER @ width.
			b_HOR: The inequality constraint vector. Each element represents an upper bound on the corresponding
			 	   value of A_HOR @ height.
			min_AR_height: list of heights obtained by multiplying the optimised widths to the minimum Aspect Ratio
			max_AR_height: list of heights obtained by multiplying the optimised widths to the maximum Aspect Ratio
			min_height_mod: list of heights obtained by taking the higher value of min_height and min_AR_height
			max_height_mod: list of heights obtained by taking the lower value of max_height and max_AR_height
	   Returns:
	      	W: List of optimised widths
	      	H: List of optimised heights
	      	status: boolean  representing success of optimization
	   """
	p = len(min_height)
	empty_ver = np.empty_like(Aeq_VER)
	empty_hor = np.empty_like(Aeq_HOR)
	b_min_VER = np.dot(np.array(min_width), -1)
	b_max_VER = np.array(max_width)
	b_min_VER = np.transpose(b_min_VER)
	b_max_VER = np.transpose(b_max_VER)
	b_min_VER = b_min_VER.astype(float)
	b_max_VER = b_max_VER.astype(float)
	b_VER = np.hstack((b_min_VER, b_max_VER))



	if not Aeq_VER.tolist():
		a = np.ones(p)
		W = []
		for i in range(p) :
			W.append([1])
		for i in range(p) :
			W.append([-1])
		l = len(W)
		ver_success = True
	else:
		value_opti_ver = scipy.optimize.linprog(f_VER,A_ub=A_VER,b_ub=b_VER,A_eq=Aeq_VER,b_eq=Beq_VER, bounds=(1,None), method='interior-point', callback=None, options=None, x0=None)
		X1=value_opti_ver['x']
		X1 = np.array([X1])
		X1 = np.transpose(X1)
		W =  (-1) * np.dot(A_VER, X1)
		l = len(W)
		width = W[0:int(l / 2)]
		width = width.reshape((1, int(l/2)))
		width = width.tolist()
		a = width[0]
		ver_success = value_opti_ver.success

	

	min_AR_height = []
	max_AR_height = []
	for i in range(0, int(l / 2)):
		min_AR_height.append(min_ar[i] * a[i])
		max_AR_height.append(max_ar[i] * a[i])

	min_height_mod = []
	max_height_mod = []
	for i in range(0, p):
		if (min_AR_height[i] > min_height[i]):
			min_height_mod.append(min_AR_height[i])
		else:
			min_height_mod.append(min_height[i])
	for i in range(0, p):
		if (max_AR_height[i] < max_height[i]):
			max_height_mod.append(max_AR_height[i])
		else:
			max_height_mod.append(max_height[i])
	flag1 = 0
	for i in range(0, p):
		if min_height_mod[i] > max_height_mod[i]:
			flag1 = 1
	if flag1 == 1:
		print(
			"For the given aspect ratio constraints and dimensions room cannot be drawn \n Rooms considering the given dimensions alone is being explored")
		b_min_HOR = np.dot(np.array(min_height), -1)
		b_max_HOR = np.array(max_height)
		b_min_HOR = np.transpose(b_min_HOR)
		b_max_HOR = np.transpose(b_max_HOR)
		b_min_HOR = b_min_HOR.astype(float)
		b_max_HOR = b_max_HOR.astype(float)
		b_HOR = np.hstack((b_min_HOR, b_max_HOR))
	else:
		b_min_HOR = np.dot(np.array(min_height_mod), -1)
		b_max_HOR = np.array(max_height_mod)
		b_min_HOR = np.transpose(b_min_HOR)
		b_max_HOR = np.transpose(b_max_HOR)
		b_min_HOR = b_min_HOR.astype(float)
		b_max_HOR = b_max_HOR.astype(float)
		b_HOR = np.hstack((b_min_HOR, b_max_HOR))

	# print(b_HOR)
	if not Aeq_HOR.tolist():
		H = []
		for i in range(p) :
			H.append([1])
		for i in range(p) :
			H.append([-1])
		hor_success = True
	else:
		value_opti_hor = scipy.optimize.linprog(f_HOR,A_ub=A_HOR,b_ub=b_HOR,A_eq=Aeq_HOR,b_eq=Beq_HOR, bounds=(1,None), method='interior-point', callback=None, options=None, x0=None)

		X2=value_opti_hor['x']
		X2 = np.array([X2])
		X2 = np.transpose(X2)
		H = (-1) * np.dot(A_HOR,X2)
		hor_success = value_opti_hor.success

	




	status =  ver_success and hor_success
	return [W, H, status]
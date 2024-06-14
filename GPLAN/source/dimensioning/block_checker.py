import numpy as np


def block_checker(E,symm_rooms):
    symm_rooms = symm_rooms.split(',')
    symm_num = len(symm_rooms)
    ret = []
    hor_rooms = []
    ver_rooms = []
    ver_list = []
    hor_list = []
    for i in range(0, symm_num):
        symm_rooms[i] = symm_rooms[i].replace('+', ' ')
        symm_rooms[i] = symm_rooms[i].replace('(', '')
        symm_rooms[i] = symm_rooms[i].replace(')', '')

    def unique(l):
        x = np.array(l)
        x = np.unique(x)
        return x.tolist()

    def isblock(l):
        list = []
        rows = len(E)
        columns = len(E[0])
        P = np.copy(E)
        for i in range(0,len(l)):
            P[P==l[i]] = -1

        left = columns
        right = 0
        top = rows
        bottom = 0
        count = 0

        for x in range(0,rows):
            for y in range(0,columns):
                if P[x][y] == -1:
                    top = min(top, x)
                    bottom = max(bottom, x)
                    left = min(left, y)
                    right = max(right, y)
                    count = count+1

        if count > 0 and count == (right - left + 1) * (bottom - top + 1):
            ver_rooms = [[top,left],[top,right]]
            hor_rooms = [[top,left],[bottom,left]]
            return [True ,ver_rooms,hor_rooms]

        return [False, [], []]

    for i in range(0, int(symm_num / 2)):

        temp1 = (symm_rooms[2 * i])
        temp1 = temp1.split(' ')
        temp1_sz = len(temp1);
        temp1 = [int(i) for i in temp1]

        temp2 = (symm_rooms[2 * i + 1]);
        temp2 = temp2.split(' ')
        temp2_sz = len(temp2);
        temp2 = [int(i) for i in temp2]

        [bool1, ver_rooms1, hor_rooms1] = isblock(temp1)
        [bool2, ver_rooms2, hor_rooms2] = isblock(temp2)

        ver_list1 = []
        hor_list1 = []
        ver_list2 = []
        hor_list2 = []

        if(bool1 and bool2):

            for j in range(ver_rooms1[0][0],ver_rooms1[1][0]+1):
                for k in range(ver_rooms1[0][1],ver_rooms1[1][1]+1):
                    ver_list1.append(E[j][k])
            ver_list1 = unique(ver_list1)

            for j in range(hor_rooms1[0][0],hor_rooms1[1][0]+1):
                for k in range(hor_rooms1[0][1],hor_rooms1[1][1]+1):
                    hor_list1.append(E[j][k])
            hor_list1 = unique(hor_list1)

            for j in range(ver_rooms2[0][0], ver_rooms2[1][0] + 1):
                for k in range(ver_rooms2[0][1], ver_rooms2[1][1] + 1):
                    ver_list2.append(E[j][k])
            ver_list2= unique(ver_list2)

            for j in range(hor_rooms2[0][0], hor_rooms2[1][0] + 1):
                for k in range(hor_rooms2[0][1], hor_rooms2[1][1] + 1):
                    hor_list2.append(E[j][k])
            hor_list2 = unique(hor_list2)

            ret.append(bool1 and bool2)
            ver_list.extend([ver_list1,ver_list2])
            hor_list.extend([hor_list1, hor_list2])

        else:
            ret.append(bool1 and bool2)

    return [all(x==True for x in ret), ver_list, hor_list]



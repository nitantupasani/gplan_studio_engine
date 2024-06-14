import tkinter as tk
# import .poly as poly
trace = 0 

class DrawOuterBoundary:

    def __init__(self,graph_data,pen,color_list):
        # def afterwork():
        #     poly.dissected(self.graph_data,self.pen,self.color_list,self.outer_boundary)
            # root.destroy()

        self.graph_data = graph_data
        self.pen = pen
        self.color_list = color_list
        root = tk.Tk()
        canvas = tk.Canvas(root, bg="white", width=600, height=400)
        
        btn = tk.Button(root, text='Submit!', width=40,
             height=5, bd='10', command=afterwork)
  
        btn.place(x=65, y=100)

        canvas.pack()
        coords = {"x":0,"y":0,"x2":0,"y2":0}
        final=[]
        lines = []

        self.outer_boundary = []
        self.previous_point = [] 
        def click(e):
            if(len(self.previous_point)==0):
                coords["x"] = e.x
                coords["y"] = e.y
            else:
                coords["x"] = self.previous_point[0]
                coords["y"] = self.previous_point[1]
                
            lines.append(canvas.create_line(coords["x"],coords["y"],coords["x"],coords["y"]))

        def release(l):
            lis=[]
            lis.append(coords["x"]);lis.append(coords["y"]);lis.append(coords["x2"]);lis.append(coords["y2"])
            self.previous_point = [coords["x2"],coords["y2"]]

            final.append(lis)

        def drag(e):
            coords["x2"] = e.x
            coords["y2"] = e.y
            canvas.coords(lines[-1], coords["x"],coords["y"],coords["x2"],coords["y2"])
            
        canvas.bind("<ButtonPress-1>", click)
        canvas.bind("<B1-Motion>", drag) 
        canvas.bind('<ButtonRelease-1>', release)
        root.mainloop()
        print(final)
        for i in range(len(final)):
            self.outer_boundary.append([final[i][2],final[i][3]])
        
        # self.outer_boundary[len(self.outer_boundary)-1][1] = self.outer_boundary[0][1]
        # first = self.outer_boundary[0]
        # for i in range(len(self.outer_boundary)-1):
            # self.outer_boundary[i] = self.outer_boundary[i+1]
        # self.outer_boundary[len(self.outer_boundary)-1] = first;
        self.outer_boundary.append([final[0][0],final[0][1]])
        # poly.dissected(self.graph_data,self.pen,self.color_list,self.outer_boundary)
        print(self.outer_boundary)
     
# DrawOuterBoundary()
# tk.mainloop()
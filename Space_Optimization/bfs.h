#ifndef BFS_H
#define BFS_H
#include <stdlib.h>
#include <string.h>

typedef struct {
    int r, c;
} Point;

typedef struct {
    Point* data;
    int front, rear, size, capacity;
} Queue;

Queue* create_queue(int capacity);
void destroy_queue(Queue* q);
int is_empty(Queue* q);
void enqueue(Queue* q, Point p);
Point dequeue(Queue* q);

int count_corridor_components(int* layout, int* region, int height, int width, int corridor_final);

void corridor_creator(int* matrix, int height, int width, int corridor_width, int corridor_final, int unusable);

#endif
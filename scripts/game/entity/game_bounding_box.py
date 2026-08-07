import pygame


class BoundingBox(pygame.Rect):
    def __init__(self, x, y, width, height):
        super().__init__(x, y, width, height)
        
    def update(self, x, y):
        self.x = x
        self.y = y
        
    def center(self):
        return self.x + self.width / 2, self.y + self.height / 2
    
    def collide(self, other):
        if self.colliderect(other):
            return True
        else:
            return False
    